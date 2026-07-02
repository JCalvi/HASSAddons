ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

RUN apk add --no-cache \
    python3 \
    openssh-client \
    sshpass \
    iputils \
    ca-certificates \
    mosquitto-clients

WORKDIR /app
COPY app/ /app/app/
COPY web/ /app/web/
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

EXPOSE 8090
CMD ["/app/run.sh"]
