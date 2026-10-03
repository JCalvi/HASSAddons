#!/usr/bin/with-contenv bashio
set -euo pipefail

bashio::log.info "Starting Actron NEO Local Cloud..."

LOCAL_IP="$(bashio::config 'local_ip')"
if [ -z "${LOCAL_IP}" ]; then
    bashio::log.fatal "The local_ip option is required. Set it to the Home Assistant host LAN IP reachable by the NEO controller(s)."
    exit 1
fi

export LOCAL_IP
export NEO_MQTT_PORT="$(bashio::config 'neo_mqtt_port')"
export TOPIC_PREFIX="$(bashio::config 'topic_prefix')"
export DISCOVERY_PREFIX="$(bashio::config 'discovery_prefix')"
export PUBLISH_RAW_STATE="$(bashio::config 'publish_raw_state')"
export LOG_LEVEL="$(bashio::config 'log_level')"

export MQTT_HOST="$(bashio::services mqtt 'host')"
export MQTT_PORT="$(bashio::services mqtt 'port')"
export MQTT_USERNAME="$(bashio::services mqtt 'username')"
export MQTT_PASSWORD="$(bashio::services mqtt 'password')"

if [ -z "${MQTT_USERNAME}" ]; then
    bashio::log.fatal "MQTT service did not provide a username. The Mosquitto Broker add-on/integration must be available."
    exit 1
fi

mkdir -p /data

# nimbus_user_id is an optional advanced bootstrap override only. The bridge
# learns the controller's real Nimbus/Actron UserId from the NEO's native MQTT
# topic once it connects, so normal installations should leave this blank.
#
# Keep the automatically generated bootstrap identity in a separate file from
# the optional override. This means clearing the option really removes the
# override instead of silently continuing to use a value persisted by an older
# add-on version.
NIMBUS_USER_ID="$(bashio::config 'nimbus_user_id')"
if [ -n "${NIMBUS_USER_ID}" ]; then
    export LOCAL_USER_ID="${NIMBUS_USER_ID}"
else
    if [ ! -s /data/generated_user_id ]; then
        cat /proc/sys/kernel/random/uuid > /data/generated_user_id
    fi
    export LOCAL_USER_ID="$(tr -d '\r\n' < /data/generated_user_id)"
fi

export CERT_FILE="/data/nimbus.crt"
export KEY_FILE="/data/nimbus.key"

if [ ! -s "${CERT_FILE}" ] || [ ! -s "${KEY_FILE}" ]; then
    bashio::log.info "Generating persistent local Nimbus TLS certificate..."
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3650 \
        -keyout "${KEY_FILE}" \
        -out "${CERT_FILE}" \
        -subj "/CN=nimbus.actronair.com.au" \
        -addext "subjectAltName=DNS:nimbus.actronair.com.au" >/dev/null 2>&1
    chmod 600 "${KEY_FILE}"
fi

cat >/etc/nginx/http.d/default.conf <<'NGINX'
server {
    listen 443 ssl;
    server_name nimbus.actronair.com.au;

    ssl_certificate     /data/nimbus.crt;
    ssl_certificate_key /data/nimbus.key;

    ssl_protocols TLSv1.2;
    ssl_ciphers 'AES256-GCM-SHA384:AES128-GCM-SHA256:AES128-SHA256:AES128-SHA';
    ssl_prefer_server_ciphers on;

    access_log /dev/stdout;
    error_log  /dev/stderr info;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host nimbus.actronair.com.au;
        proxy_set_header Connection "";
        proxy_request_buffering off;
        proxy_buffering off;
    }
}
NGINX

nginx -t
nginx

exec python3 -u /app/main.py
