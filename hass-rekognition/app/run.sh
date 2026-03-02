#!/usr/bin/with-contenv bashio

echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo "DEBUG: run.sh starting Rekognition Bridge..."

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

# 3. Map and Scrub Home Assistant Config
export HA_URL=$(bashio::config 'ha_url' | tr -d '[:space:]')
export HA_TOKEN=$(bashio::config 'ha_token' | tr -d '[:space:]')

# 4. Map Helper Entities
export HELPER_PERSON_NAME=$(bashio::config 'helper_person_name' | tr -d '[:space:]')
export HELPER_PERSON_SIMILARITY=$(bashio::config 'helper_person_similarity' | tr -d '[:space:]')
export HELPER_PERSON_STATUS=$(bashio::config 'helper_person_status' | tr -d '[:space:]')
export HELPER_DOORBELL_NAME=$(bashio::config 'helper_doorbell_name' | tr -d '[:space:]')
export HELPER_DOORBELL_SIMILARITY=$(bashio::config 'helper_doorbell_similarity' | tr -d '[:space:]')
export HELPER_DOORBELL_STATUS=$(bashio::config 'helper_doorbell_status' | tr -d '[:space:]')

echo "DEBUG: Credentials loaded for: ${AWS_ACCESS_KEY_ID:0:5}..."
echo "DEBUG: S3 Bucket: $S3_BUCKET"
echo "DEBUG: Region: $AWS_REGION"
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

# 5. Start the Web Server
# This keeps the add-on running. 'main' is the filename, 'app' is the FastAPI object.
exec uvicorn main:app --host 0.0.0.0 --port 8080
