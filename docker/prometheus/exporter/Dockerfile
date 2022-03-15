FROM python:3.8-slim

RUN apt-get update && apt-get install -y procps

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

RUN useradd --create-home --shell /bin/bash exporter
USER exporter
WORKDIR /home/exporter

COPY exporter.py .
