"""
Rekognition Bridge – per-request worker subprocess
Reads a JSON payload from stdin, executes S3 upload + Rekognition calls,
optionally updates HA helpers, optionally deletes the S3 object, and
prints a single JSON response to stdout before exiting.

Run by main.py via subprocess; inherits all environment variables.
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path

import boto3
import requests
from botocore.config import Config as BotocoreConfig

# ---------------------------------------------------------------------------
# Logging (stderr so it doesn't pollute stdout JSON)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("rekognition_worker")

# ---------------------------------------------------------------------------
# Configuration (inherited from parent process environment)
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
# AWS clients (initialised once per worker invocation)
# ---------------------------------------------------------------------------
_boto_cfg = BotocoreConfig(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2})
s3_client = boto3.client("s3", region_name=AWS_REGION, config=_boto_cfg)
rekognition_client = boto3.client("rekognition", region_name=AWS_REGION, config=_boto_cfg)


# ---------------------------------------------------------------------------
# HA helper update
# ---------------------------------------------------------------------------
def _update_ha_helper(entity_id: str, value) -> None:
    """Updates HA helpers. Sends numbers as floats to fix the 9.84% bug."""
    if not entity_id or not HA_URL or not HA_TOKEN:
        return

    parts = entity_id.split(".")
    domain = parts[0] if len(parts) > 0 else "input_text"

    if domain == "input_number":
        service = "input_number/set_value"
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
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        logger.info("Successfully updated %s to %s", entity_id, value)
    except Exception as exc:
        logger.error("Failed to update %s: %s", entity_id, exc)


def _update_ha_helpers(result: dict) -> None:
    """Routes result dict to the configured Home Assistant helpers."""
    _update_ha_helper(HELPER_PERSON_NAME, result.get("name") if result.get("name") is not None else "unknown")
    _update_ha_helper(HELPER_PERSON_SIMILARITY, result.get("similarity") if result.get("similarity") is not None else 0)
    _update_ha_helper(HELPER_PERSON_STATUS, result.get("status", "error"))


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
    """Delete an object from S3 (best-effort)."""
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


def _search_faces(s3_key: str, threshold: int, max_faces: int):
    """
    Run SearchFacesByImage via S3Object.

    Returns the top FaceMatch dict or None if no matches above threshold.
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
    matches.sort(key=lambda m: m["Similarity"], reverse=True)
    return matches[0]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception as exc:
        result = {
            "status": "error",
            "matched": False,
            "faces_detected": 0,
            "threshold": DEFAULT_THRESHOLD,
            "error_message": f"Invalid input payload: {exc}",
        }
        print(json.dumps(result))
        sys.exit(1)

    snapshot_path: str = payload.get("snapshot_path", "")
    raw_threshold = payload.get("threshold")
    threshold: int = int(raw_threshold if raw_threshold is not None else DEFAULT_THRESHOLD)
    raw_max_faces = payload.get("max_faces")
    max_faces: int = int(raw_max_faces if raw_max_faces is not None else 1)

    logger.info(
        "Worker started: snapshot=%s threshold=%d max_faces=%d",
        snapshot_path,
        threshold,
        max_faces,
    )

    s3_key = None
    try:
        s3_key = _upload_to_s3(snapshot_path)

        faces_detected = _detect_faces(s3_key)
        if faces_detected == 0:
            result = {
                "status": "no_face",
                "matched": False,
                "faces_detected": 0,
                "threshold": threshold,
            }
            _update_ha_helpers(result)
            print(json.dumps(result))
            return

        best_match = _search_faces(s3_key, threshold, max_faces)
        if best_match is None:
            result = {
                "status": "no_match",
                "matched": False,
                "faces_detected": faces_detected,
                "threshold": threshold,
            }
            _update_ha_helpers(result)
            print(json.dumps(result))
            return

        name = best_match["Face"].get("ExternalImageId")
        similarity = round(float(best_match["Similarity"]), 2)
        result = {
            "status": "matched",
            "matched": True,
            "name": name,
            "similarity": similarity,
            "faces_detected": faces_detected,
            "threshold": threshold,
        }
        _update_ha_helpers(result)
        print(json.dumps(result))

    except FileNotFoundError as exc:
        logger.error("Snapshot file not found: %s", exc)
        result = {
            "status": "error",
            "matched": False,
            "faces_detected": 0,
            "threshold": threshold,
            "error_message": str(exc),
        }
        print(json.dumps(result))
        sys.exit(1)

    except Exception as exc:
        logger.error("Unexpected error during match: %s", exc, exc_info=True)
        result = {
            "status": "error",
            "matched": False,
            "faces_detected": 0,
            "threshold": threshold,
            "error_message": str(exc),
        }
        print(json.dumps(result))
        sys.exit(1)

    finally:
        if s3_key and DELETE_AFTER_MATCH:
            _delete_from_s3(s3_key)


if __name__ == "__main__":
    main()
