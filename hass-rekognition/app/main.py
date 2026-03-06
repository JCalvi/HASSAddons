"""
Rekognition Bridge – Home Assistant local add-on (lightweight API server)

Heavy work (boto3, S3, Rekognition, HA helper updates) is delegated to a
short-lived worker subprocess (worker.py) that is spawned only when
POST /match is called.  When idle the server holds no AWS connections and
imports no heavy libraries, keeping RAM and CPU usage minimal.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _coerce_log_level(value: str) -> int:
    """
    Accepts standard logging names (DEBUG/INFO/WARNING/ERROR/CRITICAL) or numeric
    strings (10/20/30/40/50). Defaults to INFO if invalid.

    Notes:
    - Uvicorn supports TRACE, but Python's standard logging does not define TRACE.
      If the add-on config sets TRACE, we map it to DEBUG on the app side so the
      user still gets maximal verbosity from the app logger.
    """
    if value is None:
        return logging.INFO

    raw = str(value).strip()
    if not raw:
        return logging.INFO

    # Numeric levels
    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return logging.INFO

    upper = raw.upper()

    # Uvicorn supports TRACE but Python logging doesn't by default.
    # Map TRACE -> DEBUG for the app.
    if upper == "TRACE":
        return logging.DEBUG

    return getattr(logging, upper, logging.INFO)


LOG_LEVEL = _coerce_log_level(os.environ.get("LOG_LEVEL", "INFO"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("rekognition_bridge")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLD = int(os.environ.get("DEFAULT_THRESHOLD", "95"))
WORKER_TIMEOUT = int(os.environ.get("WORKER_TIMEOUT", "60"))

# When true, stream worker stderr to the server log for every request.
# When false (default), worker stderr is only emitted on failure.
LOG_WORKER_STDERR = os.environ.get("LOG_WORKER_STDERR", "false").lower() in ("true", "1", "yes")

# Optional API token; if set, requests to POST /match must include a matching header:
#   X-Rekognition-Token: <token>
API_TOKEN = os.environ.get("API_TOKEN", "").strip()

# Resolve the worker script path relative to this file so it works whether
# uvicorn is started from /app or from another working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_PATH = os.path.join(_HERE, "worker.py")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Rekognition Bridge", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class MatchRequest(BaseModel):
    snapshot_path: str
    threshold: Optional[int] = None
    max_faces: Optional[int] = 1


class MatchResponse(BaseModel):
    status: str  # matched | no_match | no_face | error
    matched: bool
    name: Optional[str] = None
    similarity: Optional[float] = None
    faces_detected: int = 0
    threshold: int
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@app.post("/match", response_model=MatchResponse)
def match(req: MatchRequest, x_rekognition_token: Optional[str] = Header(default=None)):
    threshold = req.threshold if req.threshold is not None else DEFAULT_THRESHOLD
    max_faces = req.max_faces if req.max_faces is not None else 1

    # Optional auth gate (enabled only when API_TOKEN is configured)
    if API_TOKEN and x_rekognition_token != API_TOKEN:
        return JSONResponse(
            status_code=401,
            content={
                "status": "error",
                "matched": False,
                "faces_detected": 0,
                "threshold": threshold,
                "error_message": "Unauthorized",
            },
        )

    logger.info(
        "POST /match  snapshot=%s  threshold=%d  max_faces=%d",
        req.snapshot_path,
        threshold,
        max_faces,
    )

    # Pre-flight: verify the snapshot file exists before spawning a worker.
    if not Path(req.snapshot_path).is_file():
        logger.warning("Snapshot not found (pre-flight): %s", req.snapshot_path)
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "matched": False,
                "faces_detected": 0,
                "threshold": threshold,
                "error_message": f"Snapshot not found: {req.snapshot_path}",
            },
        )

    payload = json.dumps(
        {
            "snapshot_path": req.snapshot_path,
            "threshold": threshold,
            "max_faces": max_faces,
        }
    )

    try:
        proc = subprocess.run(
            [sys.executable, WORKER_PATH],
            input=payload,
            capture_output=True,
            text=True,
            timeout=WORKER_TIMEOUT,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        logger.error("Worker timed out after %ds for snapshot=%s", WORKER_TIMEOUT, req.snapshot_path)
        return JSONResponse(
            status_code=504,
            content={
                "status": "error",
                "matched": False,
                "faces_detected": 0,
                "threshold": threshold,
                "error_message": f"Worker timed out after {WORKER_TIMEOUT}s",
            },
        )

    worker_failed = proc.returncode != 0
    if proc.stderr and (LOG_WORKER_STDERR or worker_failed):
        for line in proc.stderr.splitlines():
            line = line.strip()
            if line:
                # Keep worker stderr lines visible, but do not change worker formatting.
                logger.info("worker | %s", line)

    stdout = proc.stdout.strip()

    # Always try to parse stdout as JSON first (worker emits JSON even on error)
    if stdout:
        try:
            data = json.loads(stdout)

            # Defense in depth: if the worker reports a missing snapshot, map to 400.
            error_msg = data.get("error_message", "")
            if data.get("status") == "error" and error_msg.startswith("Snapshot not found:"):
                return JSONResponse(status_code=400, content=data)

            return MatchResponse(**data)
        except json.JSONDecodeError as exc:
            logger.error("Worker stdout is not valid JSON: %s | stdout=%r", exc, stdout)
        except Exception as exc:
            logger.error(
                "Failed to construct MatchResponse from worker output (%s): %s | stdout=%r",
                type(exc).__name__,
                exc,
                stdout,
            )

    # Worker exited non-zero and stdout was not parseable JSON
    if proc.returncode != 0:
        logger.error("Worker exited with code %d for snapshot=%s", proc.returncode, req.snapshot_path)
        return MatchResponse(
            status="error",
            matched=False,
            threshold=threshold,
            error_message=f"Worker exited with code {proc.returncode}",
        )

    # Unexpected: zero exit but no parseable output
    logger.error("Worker produced no output for snapshot=%s", req.snapshot_path)
    return MatchResponse(
        status="error",
        matched=False,
        threshold=threshold,
        error_message="Worker produced no output",
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}