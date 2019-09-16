FROM python:3.6-slim

RUN mkdir -p /app/edit_targets

WORKDIR /app/edit_targets

COPY requirements.txt /app/edit_targets
RUN pip3 install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y procps

COPY edit_targets.py /app/edit_targets

EXPOSE 8080

ENTRYPOINT ["python3.6", "edit_targets.py"]
