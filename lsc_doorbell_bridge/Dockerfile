ARG BUILD_VERSION=0.4.0
ARG BUILD_ARCH=amd64
FROM python:3.12-slim-bookworm

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

WORKDIR /app
COPY app.py tuya_message.py ha_camera.py config_ui.py /app/
COPY run.sh /run.sh
RUN chmod 0755 /run.sh

CMD ["/run.sh"]
