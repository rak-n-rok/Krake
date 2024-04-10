FROM python:3.11-slim

RUN apt update &&  \
    apt install -y --no-install-recommends git &&  \
    rm -f /var/cache/apt/archives/*.deb /var/cache/apt/archives/partial/*.deb /var/cache/apt/*.bin || true

RUN pip install --no-cache-dir pre-commit
