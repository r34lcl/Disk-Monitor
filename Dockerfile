# Ubuntu 24.04 para que zfsutils coincida con el módulo ZFS del host (2.2.2)
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 TZ=UTC
RUN apt-get update && apt-get install -y --no-install-recommends \
      smartmontools zfsutils-linux util-linux python3 python3-venv tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH=/venv/bin:$PATH DB_PATH=/data/disk-monitor.db
COPY VERSION ./
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
