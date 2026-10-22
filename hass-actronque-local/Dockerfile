FROM ghcr.io/home-assistant/base:3.23 AS builder

RUN apk add --no-cache python3 py3-pip gcc musl-dev \
    && python3 -m pip install --no-cache-dir --break-system-packages --target /opt/python paho-mqtt==2.1.0

# Compile the small 32-bit cipher on each target architecture (amd64/aarch64).
COPY app/walllink_cipher.c /tmp/walllink_cipher.c
RUN gcc -O3 -std=c11 -Wall -Wextra -Werror -fPIC -shared \
    -o /opt/libwalllink_cipher.so /tmp/walllink_cipher.c

# Fail the image build if C and Python disagree about any test frame.
COPY app/walllink_codec.py tests/test_walllink_codec.py /tmp/native-tests/
RUN cp /opt/libwalllink_cipher.so /tmp/native-tests/libwalllink_cipher.so \
    && cd /tmp/native-tests \
    && python3 -m unittest -v test_walllink_codec

FROM ghcr.io/home-assistant/base:3.23

ARG BUILD_VERSION
ARG BUILD_ARCH

RUN apk add --no-cache python3

ENV PYTHONPATH="/opt/python"

WORKDIR /app

COPY --from=builder /opt/python /opt/python
COPY app /app
COPY --from=builder /opt/libwalllink_cipher.so /app/libwalllink_cipher.so
COPY run.sh /run.sh

RUN chmod a+x /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

CMD ["/run.sh"]
