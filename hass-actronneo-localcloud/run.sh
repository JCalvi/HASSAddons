#!/usr/bin/with-contenv bashio
set -euo pipefail

ADDON_VERSION="$(bashio::addon.version)"
bashio::log.info "Starting Actron NEO Local Cloud v${ADDON_VERSION}"

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

case "${PUBLISH_RAW_STATE,,}" in
    true|1|yes|on)
        RAW_STATE_STATUS="enabled"
        ;;
    *)
        RAW_STATE_STATUS="disabled"
        ;;
esac

bashio::log.info "Configured log level: ${LOG_LEVEL}"
bashio::log.info "Raw NEO state publishing: ${RAW_STATE_STATUS}"
if [ "${LOG_LEVEL^^}" = "DEBUG" ]; then
    bashio::log.info "Raw NEO MQTT RX/TX diagnostics: enabled (16 KiB payload preview, sensitive fields redacted)"
else
    bashio::log.info "Raw NEO MQTT RX/TX diagnostics: disabled at ${LOG_LEVEL}; select DEBUG to enable"
fi

MQTT_READY=false
bashio::log.info "Waiting for Supervisor MQTT service..."

for attempt in $(seq 1 60); do
    if bashio::services.available 'mqtt' >/dev/null 2>&1; then
        MQTT_HOST="$(bashio::services mqtt 'host' 2>/dev/null || true)"
        MQTT_PORT="$(bashio::services mqtt 'port' 2>/dev/null || true)"
        MQTT_USERNAME="$(bashio::services mqtt 'username' 2>/dev/null || true)"
        MQTT_PASSWORD="$(bashio::services mqtt 'password' 2>/dev/null || true)"

        if [ -n "${MQTT_HOST}" ]             && [ -n "${MQTT_PORT}" ]             && [ -n "${MQTT_USERNAME}" ]             && [ -n "${MQTT_PASSWORD}" ]; then
            export MQTT_HOST MQTT_PORT MQTT_USERNAME MQTT_PASSWORD
            MQTT_READY=true
            bashio::log.info "MQTT service available at ${MQTT_HOST}:${MQTT_PORT}"
            break
        fi
    fi

    if [ "${attempt}" -eq 60 ]; then
        break
    fi

    if [ $((attempt % 10)) -eq 0 ]; then
        bashio::log.warning "MQTT service is still unavailable after $((attempt * 2)) seconds; continuing to wait"
    fi
    sleep 2
done

if [ "${MQTT_READY}" != "true" ]; then
    bashio::log.fatal "MQTT service did not become ready within 120 seconds. Ensure the Mosquitto Broker add-on/integration is enabled."
    exit 1
fi

mkdir -p /data

# Nimbus requires a UserId in its bootstrap response, but testing confirmed it
# does not need to be the controller's real Actron/Nimbus UUID. Keep a private,
# persistent local bootstrap identity instead. Once MQTT is established, the
# bridge learns the controller's real UserId from its native MQTT topic and uses
# that learned value for commands.
if [ ! -s /data/generated_user_id ]; then
    cat /proc/sys/kernel/random/uuid > /data/generated_user_id
fi
export LOCAL_USER_ID="$(tr -d '\r\n' < /data/generated_user_id)"

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
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection "";
        proxy_request_buffering off;
        proxy_buffering off;
    }
}
NGINX

nginx -t
nginx

exec python3 -u /app/main.py
