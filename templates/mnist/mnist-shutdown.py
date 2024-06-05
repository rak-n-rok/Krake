#!/usr/bin/env python3
"""This script is used by the mnist container to "shutdown" hook test.
It's a more practical abbreviation of the normal shutdown hook script.
"""
import os.path
import subprocess

import requests
import socketserver
from http.server import BaseHTTPRequestHandler

endpoint_env = "KRAKE_SHUTDOWN_URL"
token_env = "KRAKE_SHUTDOWN_TOKEN"
default_ca_bundle = "/etc/krake_shutdown_cert/ca-bundle.pem"
default_cert_path = "/etc/krake_shutdown_cert/cert.pem"
default_key_path = "/etc/krake_shutdown_cert/key.pem"


def shutdown_pod():

    cert_and_key = None
    ca = False
    # Only set if TLS is enabled. Otherwise, the files do not exist.
    if os.path.isfile(default_cert_path) and os.path.isfile(default_key_path):
        cert_and_key = (default_cert_path, default_key_path)
        ca = default_ca_bundle

    endpoint = os.getenv(endpoint_env)
    token = os.getenv(token_env)

    print("\nENDPOINT: " + endpoint, flush=True)
    print("\nTOKEN: " + token + "\n", flush=True)

    try:
        pgrep = subprocess.Popen(
            ("pgrep", "-fx", "python /mnist/mnist_training.py"),
            stdout=subprocess.PIPE)
        result = subprocess.run(
            ["head", "-n", "1"],
            stdin=pgrep.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )

        pid = (result.stdout).decode("utf-8")
        print("PID: " + pid, flush=True)

        result = subprocess.run(
            ["kill", "-15", pid.rstrip('\n')],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        print(result.stdout.decode("utf-8"), flush=True)
        print("Process termination requested...", flush=True)
    except Exception as e:
        print("STDERR: ", e, flush=True)

    response = requests.put(
        endpoint, verify=ca, json={"token": token}, cert=cert_and_key
    )
    print(response, flush=True)


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
