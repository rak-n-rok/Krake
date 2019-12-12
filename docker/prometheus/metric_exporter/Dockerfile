FROM python:3.6-slim

RUN mkdir -p /app/dummy_exporter

WORKDIR /app/dummy_exporter

COPY requirements.txt /app/dummy_exporter
RUN pip3 install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y procps

COPY dummy-prometheus-exporter.py /app/dummy_exporter

EXPOSE 8080

ENTRYPOINT ["python3.6", "dummy-prometheus-exporter.py"]
