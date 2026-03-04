ARG BUILD_FROM=ghcr.io/hassio-addons/base:20.0.1

# -----------------------------------------------------------------------------
# Builder: install deps with pip, but do NOT ship pip in the final image
# -----------------------------------------------------------------------------
FROM ${BUILD_FROM} AS builder

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

# Keep your existing flow/comments, but install into a staging dir
COPY requirements.txt .

# Install wheels into /install (not into the system site-packages)
RUN pip3 install --no-cache-dir --break-system-packages --prefix=/install -r requirements.txt

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

# Prune botocore service models to reduce image size (keep only what we use).
# This keeps global files (e.g., endpoints.json/partitions.json) and removes
# unused service directories under botocore/data.
#
# If you ever add more AWS services (e.g., sts, iam), add them to the keep-list.
RUN set -eux; \
    python3 -c 'import pathlib, shutil, botocore; d=pathlib.Path(botocore.__file__).parent/"data"; keep={"s3","rekognition"}; \
for p in d.iterdir(): \
    (p.is_dir() and p.name not in keep) and shutil.rmtree(p)'

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