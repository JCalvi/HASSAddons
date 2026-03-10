"""
Rekognition Bridge – Home Assistant local add-on (lightweight API server)

Heavy work (boto3, S3, Rekognition, HA helper updates) is delegated to a
short-lived worker subprocess (worker.py) that is spawned only when
POST /match is called. When idle the server holds no AWS connections and
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
      If the add-on config sets TRACE, we map it to DEBUG on the app side.
    """
    if value is None:
        return logging.INFO

    raw = str(value).strip()
    if not raw:
        return logging.INFO

    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return logging.INFO

    upper = raw.upper()
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

LOG_WORKER_STDERR = os.environ.get("LOG_WORKER_STDERR", "false").lower() in ("true", "1", "yes")
API_TOKEN = os.environ.get("API_TOKEN", "").strip()

_HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_PATH = os.path.join(_HERE, "worker.py")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Rekognition Bridge", version="1.0.0")


# ---------------------------------------------------------------------------
# Models
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


def _log_result_summary(snapshot_path: str, result: dict) -> None:
    """
    Log a concise one-line summary of the worker result at INFO.
    This keeps INFO useful without dumping full JSON every time.
    """
    status = result.get("status")
    name = result.get("name")
    similarity = result.get("similarity")
    faces = result.get("faces_detected")
    threshold = result.get("threshold")
    err = result.get("error_message")

    if status == "matched":
        try:
            sim_txt = f"{float(similarity):.1f}%"
        except Exception:
            sim_txt = str(similarity)
        logger.info(
            "Rekognition result: status=%s name=%s similarity=%s faces=%s threshold=%s snapshot=%s",
            status,
            name,
            sim_txt,
            faces,
            threshold,
            snapshot_path,
        )
    elif status in ("no_match", "no_face"):
        logger.info(
            "Rekognition result: status=%s faces=%s threshold=%s snapshot=%s",
            status,
            faces,
            threshold,
            snapshot_path,
        )
    else:
        # error or unknown
        logger.warning(
            "Rekognition result: status=%s error=%s faces=%s threshold=%s snapshot=%s",
            status,
            err,
            faces,
            threshold,
            snapshot_path,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/match", response_model=MatchResponse)
def match(req: MatchRequest, x_rekognition_token: Optional[str] = Header(default=None)):
    threshold = req.threshold if req.threshold is not None else DEFAULT_THRESHOLD
    max_faces = req.max_faces if req.max_faces is not None else 1

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
        {"snapshot_path": req.snapshot_path, "threshold": threshold, "max_faces": max_faces}
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
                logger.info("worker | %s", line)

    stdout = proc.stdout.strip()

    if stdout:
        try:
            data = json.loads(stdout)

            # DEBUG: log full JSON payload
            logger.debug("Worker JSON: %s", json.dumps(data, separators=(",", ":"), ensure_ascii=False))

            # Map worker "snapshot not found" to 400
            error_msg = data.get("error_message", "")
            if data.get("status") == "error" and error_msg.startswith("Snapshot not found:"):
                _log_result_summary(req.snapshot_path, data)
                return JSONResponse(status_code=400, content=data)

            # INFO/WARN: log a concise result summary
            _log_result_summary(req.snapshot_path, data)

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

    if proc.returncode != 0:
        logger.error("Worker exited with code %d for snapshot=%s", proc.returncode, req.snapshot_path)
        return MatchResponse(
            status="error",
            matched=False,
            threshold=threshold,
            error_message=f"Worker exited with code {proc.returncode}",
        )

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