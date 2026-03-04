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
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("rekognition_bridge")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLD = int(os.environ.get("DEFAULT_THRESHOLD", "95"))
WORKER_TIMEOUT = int(os.environ.get("WORKER_TIMEOUT", "60"))

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
    status: str          # matched | no_match | no_face | error
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
def match(req: MatchRequest) -> MatchResponse:
    threshold = req.threshold if req.threshold is not None else DEFAULT_THRESHOLD
    max_faces = req.max_faces if req.max_faces is not None else 1

    logger.info(
        "POST /match  snapshot=%s  threshold=%d  max_faces=%d",
        req.snapshot_path,
        threshold,
        max_faces,
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
        return MatchResponse(
            status="error",
            matched=False,
            threshold=threshold,
            error_message=f"Worker timed out after {WORKER_TIMEOUT}s",
        )

    if proc.stderr:
        logger.info("Worker stderr: %s", proc.stderr.strip())

    stdout = proc.stdout.strip()

    # Always try to parse stdout as JSON first (worker emits JSON even on error)
    if stdout:
        try:
            data = json.loads(stdout)
            return MatchResponse(**data)
        except json.JSONDecodeError as exc:
            logger.error("Worker stdout is not valid JSON: %s | stdout=%r", exc, stdout)
        except Exception as exc:
            logger.error("Failed to construct MatchResponse from worker output (%s): %s | stdout=%r", type(exc).__name__, exc, stdout)

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
