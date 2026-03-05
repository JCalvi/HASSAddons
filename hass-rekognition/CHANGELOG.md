# Changelog

All notable changes to this project will be documented in this file.

The format is based on **Keep a Changelog**, and this project follows **Semantic Versioning** where practical.

## [2026.3.7] - 2026-03-05
### Changed
- Trim python bytecode caches from the staged install to save a bit of space

## [2026.3.6] - 2026-03-05
### Changed
- Enable Uvicorn native extensions by default (`uvloop` event loop + `httptools` HTTP parser).
- Add Alpine builder dependencies to support compiling native Python extensions on `amd64` and `aarch64`.

## [2026.3.5] - 2026-03-05
### Added
- Pre-flight snapshot check in `main.py`: if `snapshot_path` does not exist or is not a file, the API returns `HTTP 400` immediately (no worker subprocess is spawned), with a JSON body matching the standard response schema and `error_message: "Snapshot not found: ..."`.
- Defense-in-depth: if the worker itself reports a `Snapshot not found:` error, that response is also mapped to `HTTP 400`.
- Worker timeout now returns `HTTP 504` (previously returned `HTTP 200` with `status: error`).
- New `LOG_WORKER_STDERR` environment variable (default: `false`). When `false`, worker stderr is only forwarded to the server log on failure (non-zero exit code). When `true`, each worker log line is forwarded for every request.

## [2026.3.4] - 2026-03-05
### Changed
- Reduced idle RAM/CPU by moving all heavy work (boto3, S3 upload, Rekognition API calls, HA helper updates, optional S3 deletion) into a short-lived `worker.py` subprocess spawned only when `POST /match` is called.
- The long-running API server (`main.py`) no longer imports `boto3`, `requests`, or `botocore` at startup, significantly reducing idle memory footprint.
- Added configurable `WORKER_TIMEOUT` environment variable (default: 60 s) — requests that exceed this limit return an error response instead of hanging.
- Fixed missing `DELETE_AFTER_MATCH` export in `run.sh` (was silently defaulting to `true` regardless of add-on config).
- Removed debug `echo` statements from `run.sh`.
- Added `--workers 1 --limit-concurrency 4` to the uvicorn invocation for conservative resource use.
- Removed Versions from requirements to always pull latest.
- Added Rekognition icon.

### Tradeoff
- Each `POST /match` call now incurs a Python interpreter cold-start (typically < 1 s on the host) to initialise boto3 and the AWS SDK. Given the add-on is called ~once per day this is acceptable. See README for details.

## [2026.3.3] - 2026-03-04
### Fixed
- Fixed race condition where `status` was written to the Home Assistant helper before `name` and `similarity`, causing template sensors and automations to see stale/initial values on status transitions (e.g., "matched" with name still showing "unknown"). Helpers are now updated in the order: name → similarity → status.

### Improved
- Hardened example template sensor (`hass_rekognition.yaml`) to avoid outputting the literal `unknown` state when `status == 'matched'` but the name helper has not yet settled to its final value.
- Remove pip, ensurepip, setuptools and unneeded boto modules from image to save space.
- Build from 20.0.1 base.
- Updated requirements versions.


## [2026.3.2] - 2026-03-02
### Changed
- Simplified Home Assistant helper routing: all snapshot results (doorbell or person) are now routed to the single person helper set (`helper_person_*`).
- Removed unused doorbell-specific configuration options (`helper_doorbell_name`, `helper_doorbell_similarity`, `helper_doorbell_status`) from `config.json` and `run.sh`.
- Fixed `NameError` caused by a reference to the undefined `_infer_snapshot_type` function in `main.py`.
- Changed the yaml examples to single file package to simplify install and maintenance.


## [2026.3.1] - 2026-03-02
### Added
- Added support for installing the add-on directly from the GitHub add-on repository (no manual copying into `/addons` required).
- Added Changelog.

### Changed
- Switched to building/pulling the add-on from the public GitHub repository to reduce local backup size.

### Fixed
- Fixed add-on repository validation by ensuring a top-level `repository.json` exists (required for Home Assistant Supervisor to accept the repo).
- Resolved install failures caused by GitHub authentication prompts by making the repository public.

### Removed
- Removed the unused duplicate entrypoint script:
  - `addons/rekognition_bridge/run.sh`
- Kept the active entrypoint script used by the Docker image:
  - `addons/rekognition_bridge/app/run.sh`
- Removed `armhf`, `armv7`, `i386`


## [1.0.0] - 2026-03-01
### Added
- Initial release of **Rekognition Bridge** Home Assistant add-on.
- HTTP API for submitting snapshots and returning structured face match results.
- AWS Rekognition + S3 staging bucket workflow.
- Home Assistant helper entity update support (optional).
- Multi-arch support declared in add-on config (`aarch64`, `amd64`, `armhf`, `armv7`, `i386`).
