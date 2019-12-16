FROM python:3.6-slim

RUN apt-get update && apt-get install -y procps

COPY requirements.txt .
COPY exporter.py .

RUN pip3 install --no-cache-dir -r requirements.txt
