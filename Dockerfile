FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libzbar0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .[full]

ENV LOG_LEVEL=info
ENV READ_ONLY_MODE=false
ENV MAX_IMAGE_SIZE=10485760

ENTRYPOINT ["python", "-m", "qr_reader.server"]
