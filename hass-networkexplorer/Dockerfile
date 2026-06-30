ARG BUILD_FROM=ghcr.io/hassio-addons/base:20.0.1
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    python3 \
    openssh-client \
    iputils \
    && rm -rf /usr/lib/python3.*/ensurepip \
              /usr/share/man \
              /usr/share/doc \
              /usr/share/info \
              /usr/share/locale

WORKDIR /app

COPY app/ /app/
COPY web/ /app/web/
COPY run.sh /app/run.sh

RUN chmod 755 /app/run.sh

CMD ["/app/run.sh"]