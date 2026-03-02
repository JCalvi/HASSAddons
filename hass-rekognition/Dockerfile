ARG BUILD_FROM=ghcr.io/hassio-addons/base:15.0.1
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy all files from your app folder
COPY app/ .

# Fix permissions for the run script
RUN chmod 755 /app/run.sh

# Use the S6-friendly CMD
CMD [ "/app/run.sh" ]
