# Rekognition Bridge – Home Assistant Add-on

Bridges local Home Assistant snapshots to AWS Rekognition for facial recognition and exposes an HTTP API returning structured match results.

## Features

- Upload snapshots to S3, run AWS Rekognition face detection and search.
- Returns a structured JSON response (`status`, `matched`, `name`, `similarity`, etc.).
- Optionally updates Home Assistant `input_text` / `input_number` helper entities with the result.

## Installation

Add the repository `https://github.com/JCalvi/HASSAddons` to your Home Assistant add-on store, then install **Rekognition Bridge**.
Copy the file hass_rekognition.yaml in ha_examples into your config directory and add a package line to your configuration.yaml
eg: homeassistant:
		packages: !include hass_rekognition.yaml

> **New to AWS?** See [QUICKSTART.md](QUICKSTART.md) for a step-by-step guide covering S3 bucket creation, Rekognition collection setup, IAM least-privilege policy, face enrollment CLI commands, and troubleshooting tips.

## Configuration

```json
{
  "aws_access_key_id": "AKIAxxx",
  "aws_secret_access_key": "your_secret",
  "aws_region": "ap-southeast-2",
  "rekognition_collection": "ha_known_people",
  "s3_bucket": "your-ha-rekognition-bucket",
  "s3_prefix": "snapshots/",
  "default_threshold": 95,
  "delete_after_match": true,
  "ha_url": "http://172.30.32.1:8123",
  "ha_token": "your_long_lived_token",
  "helper_person_name": "input_text.rekognition_person_name",
  "helper_person_similarity": "input_number.rekognition_person_similarity",
  "helper_person_status": "input_text.rekognition_person_status"
}
```

| Option | Description |
|---|---|
| `aws_access_key_id` | AWS IAM access key ID |
| `aws_secret_access_key` | AWS IAM secret access key |
| `aws_region` | AWS region (e.g. `ap-southeast-2`) |
| `rekognition_collection` | Rekognition face collection ID |
| `s3_bucket` | S3 bucket for staging snapshots |
| `s3_prefix` | S3 key prefix for uploaded snapshots |
| `default_threshold` | Minimum similarity (1–100) for a match |
| `delete_after_match` | Delete the S3 object after processing |
| `ha_url` | Internal Home Assistant URL |
| `ha_token` | Long-lived access token |
| `helper_person_name` | `input_text` entity to receive matched name |
| `helper_person_similarity` | `input_number` entity to receive similarity % |
| `helper_person_status` | `input_text` entity to receive status |
| `worker_timeout` | *(optional)* Max seconds to wait for the worker subprocess (default: `60`) |
| `log_worker_stderr` | *(optional)* Set to `true` to stream worker log lines for every request; when `false` (default) worker logs are only emitted on failure |

## Architecture

The add-on uses a **lightweight API server + per-request worker** design to minimise idle resource usage:

- **API server (`main.py`)** — a minimal FastAPI/uvicorn process that holds no AWS connections and imports no heavy libraries. At idle it consumes very little RAM and near-zero CPU.
- **Worker subprocess (`worker.py`)** — spawned only when `POST /match` is called. Imports `boto3`/`requests`, uploads the snapshot to S3, calls the Rekognition APIs, updates HA helpers, and exits. The subprocess lifecycle is completely contained to a single request.

**Cold-start tradeoff:** Each `/match` call incurs a brief Python interpreter startup to load boto3 (~0.5–1 s on typical hardware). This is acceptable for an add-on called ~once per day; if sub-second response latency is critical, revert to the monolithic design from v2026.3.3.

## API

### `POST /match`

```json
{
  "snapshot_path": "/media/snapshots/front_door.jpg",
  "threshold": 95,
  "max_faces": 1
}
```

**Response:**

```json
{
  "status": "matched",
  "matched": true,
  "name": "john",
  "similarity": 98.72,
  "faces_detected": 1,
  "threshold": 95
}
```

Status values: `matched`, `no_match`, `no_face`, `error`.

**HTTP status codes:**

| Condition | HTTP status |
|---|---|
| Successful result (`matched`, `no_match`, `no_face`) | `200 OK` |
| Snapshot file not found | `400 Bad Request` |
| Worker subprocess timed out | `504 Gateway Timeout` |
| Other worker errors | `200 OK` with `status: error` |

### `GET /health`

Returns `{"status": "ok"}`.