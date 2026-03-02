# Changelog

All notable changes to this project will be documented in this file.

The format is based on **Keep a Changelog**, and this project follows **Semantic Versioning** where practical.

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