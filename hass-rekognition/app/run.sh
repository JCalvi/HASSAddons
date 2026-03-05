#!/usr/bin/with-contenv bashio

# 1. Map and Scrub AWS Credentials
export AWS_ACCESS_KEY_ID=$(bashio::config 'aws_access_key_id' | tr -d '[:space:]')
export AWS_SECRET_ACCESS_KEY=$(bashio::config 'aws_secret_access_key' | tr -d '[:space:]')
export AWS_DEFAULT_REGION=$(bashio::config 'aws_region' | tr -d '[:space:]')
export AWS_REGION="$AWS_DEFAULT_REGION"

# 2. Map and Scrub S3/Rekognition Config
export REKOGNITION_COLLECTION=$(bashio::config 'rekognition_collection' | tr -d '[:space:]')
export S3_BUCKET=$(bashio::config 's3_bucket' | tr -d '[:space:]')
export S3_PREFIX=$(bashio::config 's3_prefix' | tr -d '[:space:]')
export DEFAULT_THRESHOLD=$(bashio::config 'default_threshold' | tr -d '[:space:]')
export DELETE_AFTER_MATCH=$(bashio::config 'delete_after_match' | tr -d '[:space:]')

# 3. Map and Scrub Home Assistant Config
export HA_URL=$(bashio::config 'ha_url' | tr -d '[:space:]')
export HA_TOKEN=$(bashio::config 'ha_token' | tr -d '[:space:]')

# 4. Map Helper Entities (only person helpers retained)
export HELPER_PERSON_NAME=$(bashio::config 'helper_person_name' | tr -d '[:space:]')
export HELPER_PERSON_SIMILARITY=$(bashio::config 'helper_person_similarity' | tr -d '[:space:]')
export HELPER_PERSON_STATUS=$(bashio::config 'helper_person_status' | tr -d '[:space:]')

# 4b. Optional tuning / logging
export WORKER_TIMEOUT=$(bashio::config 'worker_timeout' | tr -d '[:space:]')
export LOG_WORKER_STDERR=$(bashio::config 'log_worker_stderr' | tr -d '[:space:]')

# 4c. Optional API security
# If API_TOKEN is set, POST /match requires the header: X-Rekognition-Token: <token>
export API_TOKEN=$(bashio::config 'api_token' | tr -d '[:space:]')

# 5. Start the Web Server
# Single worker + minimal concurrency to keep idle RAM/CPU low.
# Heavy work (boto3, S3, Rekognition) is delegated to per-request worker.py subprocesses.
exec uvicorn main:app \
  --host 0.0.0.0 --port 8080 \
  --workers 1 --limit-concurrency 4 \
  --loop uvloop \
  --http httptools