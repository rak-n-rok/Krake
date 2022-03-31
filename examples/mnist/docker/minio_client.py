import logging
import os
import shutil
import types

from minio import Minio
from minio.error import S3Error

from argparse import ArgumentParser


class ExceptionDirectoryUploadError(Exception):
    """Exception raised when an error occurs during directory upload"""


class ExceptionDirectoryDownloadError(Exception):
    """Exception raised when an error occurs during directory download"""


def create_logger(logger_level):
    logger = logging.getLogger(__name__)
    logger.setLevel(logger_level)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


logger_level = logging.DEBUG
logger = create_logger(logger_level)


def upload_directory(
    minio, directory_name, source_dir, bucket_name, logger, force=False
):
    """Create a Bucket directory in the given bucket and upload the content of a local
    directory

    Args:
        minio (minio.Minio): Minio client
        directory_name (str): the name of the local directory to upload
        source_dir (str): the directory which contains the local directory to upload
        bucket_name (str): the name of the bucket on which to upload the data
        logger (logging.Logger): logger
        force (bool): Control whether to overwrite existing data on the Minio bucket
    """

    directory_path = os.path.join(source_dir, directory_name)

    logger.debug(
        f"Testing if a directory with name {directory_name} exists in {source_dir}"
    )

    if not os.path.isdir(directory_path):
        logger.error(f"{directory_path} doesn't exist")
        raise ExceptionDirectoryUploadError

    logger.debug(
        f"Testing if a subdirectory {directory_name} already exists in {bucket_name}"
    )

    list_objects = minio.list_objects(bucket_name)

    # Note that there are no such things as directories in Minio. Object keys will
    # look like "mydir/myfile"
    objects_to_delete = []
    for obj in list_objects:
        if obj.object_name.startswith(f"{directory_name}/"):
            if not force:
                logger.error(f"{directory_name} already present in {bucket_name}")
                raise ExceptionDirectoryUploadError

            # Recording the list of objects contained in the directory to overwrite
            objects_to_delete.append(obj.object_name)

    if objects_to_delete:
        logger.debug("Force flag set to True: deleting existing directory")
        for obj in objects_to_delete:
            minio.remove_object(bucket_name, obj)

    logger.debug(f"Uploading subdirectory {directory_name} in {bucket_name}")

    count_files = 0
    for file in os.scandir(directory_path):
        if not file.is_file():
            logger.debug(f"Found subdirectory {file} in {directory_name}. Uploading...")
            upload_directory(
                minio,
                os.path.join(directory_name, file.name),
                source_dir,
                bucket_name,
                logger,
                force,
            )
            continue

        try:
            minio.fput_object(bucket_name,
                              os.path.join(directory_name, file.name),
                              os.path.join(directory_path, file.name))
        except Exception as e:
            logger.error(str(e))
        count_files += 1

    logger.debug(
        f"{count_files} files from directory {directory_name} successfully uploaded in {bucket_name}"
    )


def download_directory(
    minio, directory_name, target_dir, bucket_name, logger, force
):
    """Download a directory from a Minio bucket to the local filesystem

    Note that there are no such things as directories in Minio. Object keys will look
    like "mydir/myfile"

    Args:
        minio (minio.Minio): Minio client
        directory_name (str): the name of the Minio directory to download.
        target_dir (str): the directory on the local filesystem which will host the
            downloaded bucket directory
        bucket_name (str): the name of the Minio bucket which contains the bucket
            directory to download
        logger (logging.Logger): logger
        force (bool): set to True to override any existing bucket subdirectories
    """

    target_path = os.path.join(target_dir, directory_name)

    logger.debug(f"Testing if a subdirectory {directory_name} exists in {bucket_name}")

    list_objects = minio.list_objects(bucket_name, prefix=f"{directory_name}/")

    count = 0
    for _ in list_objects:
        count += 1
    if count == 0:
        logger.error(f"No {directory_name} directory found in {bucket_name}")
        raise ExceptionDirectoryDownloadError

    logger.debug(
        f"Testing if a directory {directory_name} already exists in {target_dir}"
    )

    if os.path.exists(target_path):
        if not force:
            logger.error(
                f"A file with the name {directory_name} already exists in {target_dir}"
            )
            raise ExceptionDirectoryDownloadError

        logger.debug(
            f"Force flag set to True: deleting existing {directory_name} directory in {target_dir}"
        )

        shutil.rmtree(target_path)

    logger.debug(f"Creating directory {directory_name} in {target_dir}")

    os.makedirs(target_path)

    logger.debug(
        f"Downloading content of Minio directory to the local file system in {target_path}"
    )
    list_objects = minio.list_objects(bucket_name, prefix=f"{directory_name}/")
    for obj in list_objects:
        if isinstance(obj, types.GeneratorType):
            pass
        minio_path = os.path.split(obj.object_name)[0]
        create_subdirs(target_dir, minio_path, directory_name)

        if minio_path == "" or minio_path == directory_name:
            try:
                minio.fget_object(bucket_name, obj.object_name,
                                  os.path.join(target_dir, obj.object_name))
            except Exception as e:
                logger.error(str(e))
        else:
            try:
                download_directory(minio, os.path.join(directory_name, minio_path),
                                   target_dir, bucket_name, logger, force=True)
            except Exception as e:
                logger.error(str(e))

    logger.debug(
        f"Successfully downloaded {count} files from bucket directory {directory_name} to {target_path}"
    )


def create_subdirs(target_dir, minio_path, directory_name):
    if minio_path != directory_name:
        # There is a subir
        create_subdirs(target_dir, os.path.split(minio_path)[0], directory_name)
        if not os.path.exists(os.path.join(target_dir, minio_path)):
            os.makedirs(os.path.join(target_dir, minio_path))


def upload_directories(
    directory_names,
    bucket_name,
    source_dir,
    endpoint_url,
    minio_user,
    minio_password,
    force=False,
    **kwargs
):
    """Create subdirectories in the given bucket and upload data from corresponding
        directories on disk

    Args:
        directory_names (list): the list of names of local directory to upload.
        bucket_name (str): the name of the Minio bucket in which to create corresponding
            bucket subdirectories.
        source_dir (str): the directory on the local filesystem which contains all
            subdirectories listed in `directory_names`.
        endpoint_url (str):
        minio_user (str):
        minio_password (str):
        force (bool): set to True to override any existing bucket subdirectories
    """

    logger.debug("Creating Minio client")

    try:
        minio_client = Minio(
            endpoint_url,
            access_key=minio_user,
            secret_key=minio_password,
            # Hardcoded insecure (http) connection
            secure=False,
        )
    except ValueError:
        minio_client = Minio(
            endpoint_url,
            access_key=minio_user,
            secret_key=minio_password,
            # Hardcoded insecure (http) connection
            secure=False,
        )

    # Retrieve the list of existing buckets
    list_buckets_response = minio_client.list_buckets()

    logger.debug(f"Testing if bucket {bucket_name} exists")

    found = False
    for bucket in list_buckets_response["Buckets"]:
        if bucket_name == bucket["Name"]:
            found = True
            break

    if not found:
        logger.error(f"Bucket {bucket_name} doesn't exist. Failed to upload any data")
        exit(1)

    upload_failed = []
    upload_sucess = []

    for directory_name in directory_names:
        try:
            upload_directory(
                minio_client,
                directory_name,
                source_dir,
                bucket_name,
                logger,
                force
            )
        except ExceptionDirectoryUploadError:
            upload_failed.append(directory_name)
        else:
            upload_sucess.append(directory_name)
            minio_client.put_object(
                bucket_name,
                os.path.join(directory_name, 'upload.done')
            )

    if upload_sucess:
        logger.info(f"Successfully uploaded {', '.join(upload_sucess)}")
    if upload_failed:
        logger.error(f"Failed to upload {', '.join(upload_failed)}")


def download_directories(
    directory_names,
    bucket_name,
    target_dir,
    endpoint_url,
    minio_user,
    minio_password,
    force=False,
    **kwargs
):
    """Download a list of directories

    Args:
        directory_names (list): the list of directories to download from Minio.
        bucket_name (str): the bucket containing the desired directories
        target_dir (str): the directory on the local filesystem in which to download
            the bucket directories. A subdirectory will be created for the content of
            the bucket directory.
        endpoint_url (str):
        minio_user (str):
        minio_password (str):
        force (bool): control whether to overwrite existing data on the local file
            system if any
    """

    logger.debug("Creating Minio client")

    try:
        minio_client = Minio(
            endpoint_url,
            access_key=minio_user,
            secret_key=minio_password,
            # Hardcoded insecure (http) connection
            secure=False,
        )
    except ValueError:
        minio_client = Minio(
            access_key=minio_user,
            secret_key=minio_password,
            # Hardcoded insecure (http) connection
            secure=False,
        )

    # Retrieve the list of existing buckets
    list_buckets_response = minio_client.list_buckets()

    download_failed = []
    download_sucess = []

    for directory_name in directory_names:

        try:
            download_directory(
                minio_client,
                directory_name,
                target_dir,
                bucket_name,
                logger,
                force
            )
        except ExceptionDirectoryDownloadError:
            download_failed.append(directory_name)
            raise
        else:
            download_sucess.append(directory_name)

    if download_sucess:
        logger.info(f"Successfully downloaded {', '.join(download_sucess)}")
    if download_failed:
        logger.error(f"Failed to download {', '.join(download_failed)}")


parser = ArgumentParser(description="Manage Minio bucket")

subparsers = parser.add_subparsers()

upload = subparsers.add_parser("upload")
upload.add_argument("-d", "--directory_names", nargs="+", required=True)
upload.add_argument("-s", "--source_dir", type=str, required=True)
upload.add_argument("-b", "--bucket_name", type=str, required=True)
upload.add_argument("-e", "--encryption_key", type=str, required=True)
upload.add_argument("-u", "--endpoint_url", type=str)
upload.add_argument("--force", action="store_true")
upload.set_defaults(func=upload_directories)

download = subparsers.add_parser("download")
download.add_argument("-d", "--directory_names", nargs="+", required=True)
download.add_argument("-t", "--target_dir", type=str, required=True)
download.add_argument("-b", "--bucket_name", type=str, required=True)
download.add_argument("-e", "--encryption_key", type=str, required=True)
download.add_argument("-u", "--endpoint_url", type=str)
download.add_argument("--force", action="store_true")
download.set_defaults(func=download_directories)

if __name__ == "__main__":
    args = parser.parse_args()
    vargs = vars(args)

    args.func(**vargs)
