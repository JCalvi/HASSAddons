FROM ghcr.io/home-assistant/base:3.23

ARG BUILD_VERSION
ARG BUILD_ARCH

RUN apk add --no-cache python3 py3-pip \
    && python3 -m pip install --no-cache-dir --break-system-packages paho-mqtt==2.1.0

WORKDIR /app

COPY app /app
COPY run.sh /run.sh

RUN chmod a+x /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

CMD ["/run.sh"]
