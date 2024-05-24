FROM python:3.11-slim

RUN apt update &&  \
    apt install -y --no-install-recommends git gcc python3-dev &&  \
    rm -f /var/cache/apt/archives/*.deb /var/cache/apt/archives/partial/*.deb /var/cache/apt/*.bin || true

ENV PATH="/opt/venv/bin:${PATH}"
RUN python3 -m venv /opt/venv && \
    pip install --no-cache-dir pre-commit
