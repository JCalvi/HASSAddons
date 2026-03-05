ARG BUILD_FROM=ghcr.io/hassio-addons/base:20.0.1

# -----------------------------------------------------------------------------
# Builder: install deps with pip, but do NOT ship pip in the final image
# -----------------------------------------------------------------------------
FROM ${BUILD_FROM} AS builder

RUN apk add --no-cache \
    python3 \
    py3-pip \
    build-base \
    python3-dev \
    libffi-dev \
    openssl-dev \
    libuv-dev

WORKDIR /app

# Keep your existing flow/comments, but install into a staging dir
COPY requirements.txt .

# Install wheels into /install (not into the system site-packages)
RUN pip3 install --no-cache-dir --break-system-packages --prefix=/install -r requirements.txt

# Prune botocore service models to reduce image size (keep only what we use).
# This runs in the builder so the deleted files never get copied into the final image.
#
# If you ever add more AWS services (e.g., sts, iam), add them to the keep-list.
RUN set -eux; \
    # Find botocore/data inside the staged /install prefix (works across Python minor versions)
    BOTODIR="$(find /install -type d -path "*/site-packages/botocore/data" -print -quit)"; \
    echo "botocore data dir in staged prefix: ${BOTODIR:-<not found>}"; \
    test -n "$BOTODIR"; \
    find "$BOTODIR" -maxdepth 1 -mindepth 1 -type d \
      ! -name 's3' \
      ! -name 'rekognition' \
      ! -name 'sts' \
      -exec rm -rf {} +

# -----------------------------------------------------------------------------
# Final: python runtime only + copied deps
# -----------------------------------------------------------------------------
FROM ${BUILD_FROM}

# python3 runtime only (no py3-pip)
RUN apk add --no-cache python3

WORKDIR /app

# Copy python deps and console scripts from builder stage
COPY --from=builder /install/ /usr/

# Copy all files from your app folder
COPY app/ .

# Remove ensurepip (pip is not shipped in the final image) and trim /usr/share
# to reduce runtime image size. (Keep this AFTER copying /install so we don't
# accidentally remove something pip might rely on during build steps.)
#
# This version is resilient to Python minor-version changes (e.g., 3.11 -> 3.12).
RUN set -eux; \
    rm -rf /usr/lib/python3.*/ensurepip; \
    rm -rf /usr/share/man /usr/share/doc /usr/share/info /usr/share/locale

# Fix permissions for the run script
RUN chmod 755 /app/run.sh

# Use the S6-friendly CMD
CMD [ "/app/run.sh" ]