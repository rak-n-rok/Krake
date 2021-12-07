#!/usr/bin/env python3
"""This script is used by the "complete" hook test, to act as a dummy job being started
in a Deployment that belongs to a Krake Application.
"""
import os.path
import signal
import time

import requests
import socketserver
from http.server import BaseHTTPRequestHandler

endpoint_env = "KRAKE_SHUTDOWN_URL"
token_env = "KRAKE_TOKEN"
default_ca_bundle = "/etc/krake_cert/ca-bundle.pem"
default_cert_path = "/etc/krake_cert/cert.pem"
default_key_path = "/etc/krake_cert/key.pem"


def shutdown_pod():

    cert_and_key = None
    ca = False
    # Only set if TLS is enabled. Otherwise the files do not exist.
    if os.path.isfile(default_cert_path) and os.path.isfile(default_key_path):
        cert_and_key = (default_cert_path, default_key_path)
        ca = default_ca_bundle

    endpoint = os.getenv(endpoint_env)
    token = os.getenv(token_env)

    print(endpoint)
    print(token)

    time.sleep(10)

    response = requests.put(
        endpoint, verify=ca, json={"token": token}, cert=cert_and_key
    )
    print(response)


class ShutdownRequestHandler(BaseHTTPRequestHandler):
    def do_PUT(self):
        if self.path == '/shutdown':
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length",
                             str(len(b'Graceful shutdown requested!')))
            self.end_headers()
            self.wfile.write(b'Graceful shutdown requested!')
            shutdown_pod()


def main():
    httpd = socketserver.TCPServer(("", 10000), ShutdownRequestHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
