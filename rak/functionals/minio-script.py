import os
import time

from pathlib import Path
from minio import Minio
from minio.error import S3Error


CI_BUCKET = "krake-ci-bucket"
TEST_FILE_PATH = Path("/tmp") / ("krake_ci_file_" + time.strftime("%Y%m%d_%H_%M_%S"))


def main():
    # Create a client with the MinIO server playground, its access key
    # and secret key.
    client = Minio(
        os.getenv("MINIO_ENDPOINT"),
        access_key=os.getenv("MINIO_ROOT_USER"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD"),
        # Hardcoded insecure (http) connection
        secure=False,
    )

    # Make bucket if not exist.
    found = client.bucket_exists(CI_BUCKET)
    if not found:
        client.make_bucket(CI_BUCKET)
    else:
        print(f"Bucket {CI_BUCKET} already exists")

    # Create test file to be uploaded
    with open(TEST_FILE_PATH, "w") as f:
        f.write("Hello Krake CI pipeline!!!")

    # Upload test file to the bucket
    client.fput_object(
        CI_BUCKET, TEST_FILE_PATH.name, TEST_FILE_PATH,
    )
    print(
        f"{TEST_FILE_PATH} is successfully uploaded as "
        f"object {TEST_FILE_PATH.name} to bucket {CI_BUCKET}."
    )

    # Ensure that object is uploaded
    objects = list(client.list_objects(CI_BUCKET))
    assert len(objects) == 1
    obj, *_ = objects
    assert obj.object_name == TEST_FILE_PATH.name


if __name__ == "__main__":
    try:
        main()
    except S3Error as exc:
        print("error occurred.", exc)
