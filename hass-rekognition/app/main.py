"""
Rekognition Bridge – Home Assistant local add-on
POST /match  →  upload snapshot to S3, detect faces, search faces, return result
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import boto3
import requests
from fastapi import FastAPI, HTTPException
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
# Configuration (injected via environment variables set by run.sh)
# ---------------------------------------------------------------------------
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
REKOGNITION_COLLECTION = os.environ.get("REKOGNITION_COLLECTION", "ha_known_people")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PREFIX = os.environ.get("S3_PREFIX", "snapshots/").rstrip("/") + "/"
DEFAULT_THRESHOLD = int(os.environ.get("DEFAULT_THRESHOLD", "95"))
DELETE_AFTER_MATCH = os.environ.get("DELETE_AFTER_MATCH", "true").lower() in ("true", "1", "yes")

HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

HELPER_PERSON_NAME = os.environ.get("HELPER_PERSON_NAME", "")
HELPER_PERSON_SIMILARITY = os.environ.get("HELPER_PERSON_SIMILARITY", "")
HELPER_PERSON_STATUS = os.environ.get("HELPER_PERSON_STATUS", "")

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
s3_client = boto3.client("s3", region_name=AWS_REGION)
rekognition_client = boto3.client("rekognition", region_name=AWS_REGION)

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
# Helper: update a Home Assistant input_* entity via REST API
# ---------------------------------------------------------------------------
def _update_ha_helper(entity_id: str, value) -> None:
    """Updates HA helpers. Sends numbers as floats to fix the 9.84% bug."""
    if not entity_id or not HA_URL or not HA_TOKEN:
        return

    # Extract the domain (e.g., 'input_number') safely as a string
    parts = entity_id.split(".")
    domain = parts[0] if len(parts) > 0 else "input_text"
    
    if domain == "input_number":
        service = "input_number/set_value"
        # Convert to float and round to 2 decimal places (e.g., 99.84)
        try:
            numeric_value = round(float(value), 2)
        except (ValueError, TypeError):
            numeric_value = 0.0
        payload = {"entity_id": entity_id, "value": numeric_value}
    else:
        service = "input_text/set_value"
        payload = {"entity_id": entity_id, "value": str(value)}

    url = f"{HA_URL}/api/services/{service}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    
    try:
        # 'json=payload' is critical: it sends the number without quotes
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        logger.info("Successfully updated %s to %s", entity_id, value)
    except Exception as exc:
        logger.error("Failed to update %s: %s", entity_id, exc)

def _update_ha_helpers(snapshot_path: str, result: MatchResponse) -> None:
    """Routes results to the configured Home Assistant helpers.

    All snapshot types are routed to the person helpers (single set).
    """
    h_name = HELPER_PERSON_NAME
    h_sim = HELPER_PERSON_SIMILARITY
    h_stat = HELPER_PERSON_STATUS

    # Ensure name and similarity are written first so status flips do not cause
    # the template sensor/automations to see stale values.
    _update_ha_helper(h_name, result.name or "unknown")
    _update_ha_helper(h_sim, result.similarity or 0)

    # Finally update status
    _update_ha_helper(h_stat, result.status)


# ---------------------------------------------------------------------------
# Core recognition logic
# ---------------------------------------------------------------------------
def _upload_to_s3(local_path: str) -> str:
    """Upload snapshot file to S3 and return the S3 key."""
    file_path = Path(local_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Snapshot not found: {local_path}")

    s3_key = f"{S3_PREFIX}{uuid.uuid4().hex}_{file_path.name}"
    logger.info("Uploading %s → s3://%s/%s", local_path, S3_BUCKET, s3_key)
    s3_client.upload_file(str(file_path), S3_BUCKET, s3_key)
    return s3_key


def _delete_from_s3(s3_key: str) -> None:
    """Delete an object from S3."""
    try:
        s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        logger.info("Deleted s3://%s/%s", S3_BUCKET, s3_key)
    except Exception as exc:
        logger.warning("Failed to delete s3://%s/%s: %s", S3_BUCKET, s3_key, exc)


def _detect_faces(s3_key: str) -> int:
    """Run DetectFaces via S3Object and return the number of faces found."""
    response = rekognition_client.detect_faces(
        Image={"S3Object": {"Bucket": S3_BUCKET, "Name": s3_key}},
        Attributes=["DEFAULT"],
    )
    count = len(response.get("FaceDetails", []))
    logger.info("DetectFaces found %d face(s) in s3://%s/%s", count, S3_BUCKET, s3_key)
    return count


def _search_faces(s3_key: str, threshold: int, max_faces: int) -> Optional[dict]:
    """
    Run SearchFacesByImage via S3Object.

    Returns the top FaceMatch dict (with Face.ExternalImageId and Similarity)
    or None if no matches above threshold.
    """
    response = rekognition_client.search_faces_by_image(
        CollectionId=REKOGNITION_COLLECTION,
        Image={"S3Object": {"Bucket": S3_BUCKET, "Name": s3_key}},
        MaxFaces=max_faces,
        FaceMatchThreshold=float(threshold),
    )
    matches = response.get("FaceMatches", [])
    logger.info(
        "SearchFacesByImage returned %d match(es) above threshold %d",
        len(matches),
        threshold,
    )
    if not matches:
        return None
    # Sort descending by similarity and return the best match
    matches.sort(key=lambda m: m["Similarity"], reverse=True)
    return matches[0]


# ---------------------------------------------------------------------------
# API endpoint
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

    s3_key: Optional[str] = None
    try:
        # 1. Upload
        s3_key = _upload_to_s3(req.snapshot_path)

        # 2. DetectFaces to determine whether any face is present
        faces_detected = _detect_faces(s3_key)
        if faces_detected == 0:
            result = MatchResponse(
                status="no_face",
                matched=False,
                faces_detected=0,
                threshold=threshold,
            )
            _update_ha_helpers(req.snapshot_path, result)
            return result

        # 3. SearchFacesByImage against the Rekognition collection
        best_match = _search_faces(s3_key, threshold, max_faces)
        if best_match is None:
            result = MatchResponse(
                status="no_match",
                matched=False,
                faces_detected=faces_detected,
                threshold=threshold,
            )
            _update_ha_helpers(req.snapshot_path, result)
            return result

        name = best_match["Face"].get("ExternalImageId")
        similarity = round(float(best_match["Similarity"]), 2)
        result = MatchResponse(
            status="matched",
            matched=True,
            name=name,
            similarity=similarity,
            faces_detected=faces_detected,
            threshold=threshold,
        )
        _update_ha_helpers(req.snapshot_path, result)
        return result

    except FileNotFoundError as exc:
        logger.error("Snapshot file not found: %s", exc)
        return MatchResponse(
            status="error",
            matched=False,
            threshold=threshold,
            error_message=str(exc),
        )
    except Exception as exc:
        logger.error("Unexpected error during match: %s", exc, exc_info=True)
        return MatchResponse(
            status="error",
            matched=False,
            threshold=threshold,
            error_message=str(exc),
        )
    finally:
        if s3_key and DELETE_AFTER_MATCH:
            _delete_from_s3(s3_key)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
