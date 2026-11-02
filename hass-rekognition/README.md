# Rekognition Bridge – Home Assistant App

Bridges local Home Assistant snapshots to AWS Rekognition for facial recognition and exposes an HTTP API returning structured match results.

## Features

- Upload snapshots to S3, run AWS Rekognition face detection and search.
- Returns a structured JSON response (`status`, `matched`, `name`, `similarity`, etc.).
- Optionally updates Home Assistant `input_text` / `input_number` helper entities with the result.
- Optional API token to prevent unauthorized calls to `POST /match`.
- Configurable log level for easier troubleshooting.

## Installation

Add the repository `https://github.com/JCalvi/HASSAddons` to your Home Assistant app store, then install **Rekognition Bridge**.
Copy the file hass_rekognition.yaml in ha_examples into your config directory and add a package line to your configuration.yaml
For example, the supplied file already contains the named package wrapper:

```yaml
homeassistant:
  packages: !include hass_rekognition.yaml
```

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
  "helper_person_name": "input_text.rekognition_person_name",
  "helper_person_similarity": "input_number.rekognition_person_similarity",
  "helper_person_status": "input_text.rekognition_person_status",
  "worker_timeout": 60,
  "log_worker_stderr": false,
  "api_token": "",
  "log_level": "INFO"
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
| `helper_person_name` | `input_text` entity to receive matched name |
| `helper_person_similarity` | `input_number` entity to receive similarity % |
| `helper_person_status` | `input_text` entity to receive status |
| `worker_timeout` | *(optional)* Max seconds to wait for the worker subprocess (default: `60`) |
| `log_worker_stderr` | *(optional)* Set to `true` to stream worker log lines for every request; when `false` (default) worker logs are only emitted on failure |
| `api_token` | *(optional)* If set, `POST /match` requires header `X-Rekognition-Token` to match this value |
| `log_level` | *(optional)* Logging verbosity for the app (TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL). Default: `INFO`. |

## Security: Rekognition API token (recommended)

This token protects the Rekognition Bridge's own HTTP API and is separate
from Home Assistant authentication.

If you set `api_token` in the app configuration, the app will require this HTTP header on `POST /match`:

- Header name: `X-Rekognition-Token`
- Header value: your configured token

### Home Assistant: store token in `secrets.yaml`

Add this to your Home Assistant `secrets.yaml`:

```yaml
rekognition_bridge_token: "your-long-random-token"
```

Then in the `rest_command` (see `ha_examples/hass_rekognition.yaml`), send the header:

```yaml
headers:
  Content-Type: "application/json"
  X-Rekognition-Token: !secret rekognition_bridge_token
```

If you do **not** set `api_token` in the app, the header is not required.

## Recommended operation, retention and privacy

Snapshots leave your network and are processed by AWS. Use a private S3 staging bucket with **Block Public Access**, default encryption and a **one-day lifecycle expiration rule for the configured snapshot prefix**. Keep `delete_after_match: true`; lifecycle expiry is a backstop for failed cleanup, not a strict 24-hour deletion guarantee. If the bucket has versioning enabled or suspended, noncurrent versions need their own expiration rule. The [AWS quickstart](QUICKSTART.md#staging-bucket-retention-backstop) includes commands and explains what is retained.

Trigger recognition from a **person-detected event or doorbell press**, not a recurring timer or every video frame. The [automation example](ha_examples/automations.yaml) combines both triggers into one notification-only automation with a shared cooldown and no overlapping calls. Choose one trigger or keep both; adjust the entities, snapshot path and cooldown for your installation.

**A match is a hint, not a key.** Use recognition for notifications or human review. This app does not perform liveness checks, and increasing the similarity threshold may not make it suitable as the sole means of unlocking a door or disarming an alarm. Poor light, blur and camera angle affect matching. A similarity score is not a calibrated probability of identity.

For any consequential workflow, require independent authentication/approval. No match, no face, a missing/malformed response, an HTTP error or timeout must leave the protected action unperformed. Never reuse a previous successful helper value as the result of a new request: helpers may retain an earlier value when a request fails before they are updated. The example checks the current HTTP response, `status`, `matched`, name and score before sending a matched-person notification.

Before enrolling housemates or visitors, explain the purpose, AWS processing and retention, obtain their informed consent, and check the requirements that apply to your use. Provide a way to withdraw and delete **all enrolled FaceIds** for a person, including multiple reference images. Deleting a staged S3 image does not remove enrolled face vectors; deleting face vectors does not remove local snapshots, enrollment images, logs, backups or notification copies. See the [individual deletion procedure](QUICKSTART.md#remove-an-enrolled-person) and [AWS biometric notice and consent terms](https://aws.amazon.com/legal/biometric-notice-and-consent-terms/).

AWS describes additional service-side input retention, AI-services opt-out and deletion-request options in its [Rekognition FAQ](https://aws.amazon.com/rekognition/faqs/). S3 cleanup and `DeleteFaces` alone are not a promise that every service-side copy has been removed.

## Request volume, cost and timing

The current worker calls **DetectFaces once per successfully uploaded snapshot**, and **SearchFacesByImage once if a face was detected**. With faces in every snapshot, 10 snapshots/day over 30 days means 300 calls to each API (600 total); 100/day means 3,000 calls to each (6,000 total), before retries. These are illustrations, not my measured daily usage.

Use the [current regional Rekognition pricing](https://aws.amazon.com/rekognition/pricing/) and include face-vector storage, enrollment calls, S3 requests/storage, retries, applicable data transfer and any other configured services. One snapshot is not necessarily one billable API call. Set an AWS budget/alert and monitor usage; an alert is not a hard spending cap.

I've measured the call-to-result time at **under one second on my installation**. To measure yours, time the action in an automation trace or use curl's `time_total` for the HTTP call. Include successful and unsuccessful requests and avoid presenting a few fast results as a latency guarantee. A timeout can happen after AWS has already processed a request, so retries may add billable calls.

## Logging

To change verbosity, set `log_level` in the app configuration:

- `TRACE` for maximum verbosity (very noisy). Enables uvicorn trace-level logging; the app logger treats `TRACE` as `DEBUG`.
- `DEBUG` for detailed troubleshooting
- `INFO` for normal operation (default)
- `WARNING` / `ERROR` / `CRITICAL` for quieter logs

The app passes this value through to uvicorn via `--log-level`, so it affects both
uvicorn logs and the app logger.

## Architecture

The app uses a **lightweight API server + per-request worker** design to minimise idle resource usage:

- **API server (`main.py`)** — a minimal FastAPI/uvicorn process that holds no AWS connections and imports no heavy libraries. At idle it consumes very little RAM and near-zero CPU.
- **Worker subprocess (`worker.py`)** — spawned only when `POST /match` is called. Imports `boto3`/`requests`, uploads the snapshot to S3, calls the Rekognition APIs, updates HA helpers, and exits. The subprocess lifecycle is completely contained to a single request.

Each request starts a worker, so worker startup is included in the total request time. **I’ve measured less than one second from the automation call to its result on my installation.** This is a report from that installation, not a guaranteed response time or a cross-hardware benchmark. Network latency, image size, AWS region, host performance and optional helper updates can affect it. Camera capture before the call and notification delivery afterwards are separate.

I haven’t published a measured daily snapshot count or representative monthly bill. Use your actual event volume when estimating cost; do not infer one request per day from the worker design.

## API

### `POST /match`

```json
{
  "snapshot_path": "/media/snapshots/front_door.jpg",
  "threshold": 95,
  "max_faces": 1
}
```

**Request headers (only if `api_token` is set):**

- `X-Rekognition-Token: <your token>`

### `GET /health`

Returns `{"status": "ok"}`.
