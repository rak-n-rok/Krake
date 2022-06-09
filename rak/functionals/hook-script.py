#!/usr/bin/env python3
"""This script is used by the "complete" hook test, to act as a dummy job being started
in a Deployment that belongs to a Krake Application.
"""
import os.path
import requests

endpoint_env = "KRAKE_COMPLETE_URL"
token_env = "KRAKE_COMPLETE_TOKEN"
default_ca_bundle = "/etc/krake_complete_cert/ca-bundle.pem"
default_cert_path = "/etc/krake_complete_cert/cert.pem"
default_key_path = "/etc/krake_complete_cert/key.pem"


def main():
    print("Start script's main")

    cert_and_key = None
    ca = False
    # Only set if TLS is enabled. Otherwise the files do not exist.
    if os.path.isfile(default_cert_path) and os.path.isfile(default_key_path):
        cert_and_key = (default_cert_path, default_key_path)
        ca = default_ca_bundle
        print(f"CA:                  {ca}")
        print(f"Certificate:         {cert_and_key[0]}")
        print(f"key:                 {cert_and_key[1]}")
    else:
        print("CA:                  none")
        print("Certificate:         none")
        print("key:                 none")

    endpoint = os.getenv(endpoint_env)
    token = os.getenv(token_env)

    print(f"KRAKE_COMPLETE_URL:  {endpoint}")
    print(f"KRAKE_COMPLETE_TOKEN:{token}")

    response = requests.put(
        endpoint, verify=ca, json={"token": token}, cert=cert_and_key
    )
    assert response.status_code == 200, f"Error in response: {response.text}"
    print("End of script's main")


if __name__ == "__main__":
    main()
