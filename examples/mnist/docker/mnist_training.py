from tensorflow.keras.datasets import mnist
from tensorflow.keras.utils import to_categorical
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Conv2D
from tensorflow.keras.layers import MaxPooling2D
from tensorflow.keras.layers import Dense
from tensorflow.keras.layers import Flatten
from tensorflow.keras.optimizers import SGD
from tensorflow.keras.callbacks import ModelCheckpoint
from keras.models import load_model


from time import sleep
import os.path
import os
import threading
import multiprocessing
import signal
import re
import sys
import requests
from minio import Minio
from minio.error import S3Error

import minio_client as minio_c

CI_BUCKET = "krake-ci-bucket"

pid = os.getpid()

# set local & remote filepath
local_filepath = "checkpoint"
# create logger
logger = minio_c.create_logger('INFO')

minio_endpoint = None
if minio_endpoint is None:
    krake_shutdown_url = os.getenv("KRAKE_SHUTDOWN_URL")
    ip = krake_shutdown_url.split(":")
    minio_endpoint = ip[1].strip("/") + ":9000"

minio_user = os.getenv("MINIO_ROOT_USER")
if minio_user is None:
    minio_user = "minio-user"

minio_pw = os.getenv("MINIO_ROOT_PASSWORD")
if minio_pw is None:
    minio_pw = "minio-user-super-secret"

minio_client = Minio(
    minio_endpoint,
    access_key=minio_user,
    secret_key=minio_pw,
    # Hardcoded insecure (http) connection
    secure=False,
)

found = minio_client.bucket_exists(CI_BUCKET)
if not found:
    minio_client.make_bucket(CI_BUCKET)
else:
    print(f"Bucket {CI_BUCKET} already exists")

try:
    minio_c.download_directory(minio_client,
                              directory_name="",
                              target_dir=local_filepath,
                              bucket_name=f"{CI_BUCKET}",
                              logger=logger,
                              force=True)
except Exception as e:
    print("Error: " + str(e))
    print('Download was not possible or no data to download.')
    pass

try:
    with open('checkpoint/out.txt', 'r') as file:
        trained_epochs = file.read()
except:
    trained_epochs = None

final_fit = False
history = ""
accuracy = ""

local_filepath = "checkpoint"


class log_console_output(object):
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()  # If you want the output to be visible immediately

    def flush(self):
        for f in self.files:
            f.flush()


def reg_ex_epoch(out):
    target = out
    result = re.findall(r"Epoch\s(\d+)", target)
    return result[-1]


class ExitSignal(Exception):
    pass


def sigterm_handler(signum, frame):
    raise ExitSignal


# load train and test dataset
def load_dataset():
    # load dataset
    (trainX, trainY), (testX, testY) = mnist.load_data()
    # reshape dataset to have a single channel
    trainX = trainX.reshape((trainX.shape[0], 28, 28, 1))
    testX = testX.reshape((testX.shape[0], 28, 28, 1))
    # one hot encode target values
    trainY = to_categorical(trainY)
    testY = to_categorical(testY)
    return trainX, trainY, testX, testY


# scale pixels
def prep_pixels(train, test):
    # convert from integers to floats
    train_norm = train.astype('float32')
    test_norm = test.astype('float32')
    # normalize to range 0-1
    train_norm = train_norm / 255.0
    test_norm = test_norm / 255.0
    # return normalized images
    return train_norm, test_norm


# define cnn model
def define_model():
    model = Sequential()
    model.add(Conv2D(32, (3, 3), activation='relu', kernel_initializer='he_uniform',
                     input_shape=(28, 28, 1)))
    model.add(MaxPooling2D((2, 2)))
    model.add(Flatten())
    model.add(Dense(100, activation='relu', kernel_initializer='he_uniform'))
    model.add(Dense(10, activation='softmax'))
    # compile model
    opt = SGD(learning_rate=0.01, momentum=0.9)
    model.compile(optimizer=opt, loss='categorical_crossentropy', metrics=['accuracy'])
    return model


# evaluate a model
def evaluate_model(trainX, trainY, testX, testY, filepath, trained_epochs):
    global final_fit, history, accuracy
    # define model
    model = define_model()
    # fit model
    EPOCHS = 5
    print(filepath)
    if os.path.isfile('checkpoint/saved_model.pb'):

        loaded_model = load_model(filepath)

        try:
            trained_epochs = reg_ex_epoch(trained_epochs)
        except:
            print('out.txt was corrupted, trained epochs force set to 1.')
            trained_epochs = 1
        checkpoint = ModelCheckpoint(filepath, period=1, monitor='val_accuracy',
                                     verbose=1, save_best_only=False, mode='max')
        callbacks_list = [checkpoint]
        history = loaded_model.fit(trainX, trainY, epochs=EPOCHS, batch_size=32,
                                   initial_epoch=int(trained_epochs),
                                   validation_data=(testX, testY),
                                   callbacks=callbacks_list, verbose=1)

        # evaluate model
        acc = loaded_model.evaluate(testX, testY, verbose=0)
        #for i in range(len(acc)):
        print(f'Accuracy: {round(acc[1] * 100,2)} %')
        final_fit = True
    else:
        checkpoint = ModelCheckpoint(filepath, period=1, monitor='val_accuracy',
                                     verbose=1, save_best_only=False, mode='max')
        callbacks_list = [checkpoint]
        history = model.fit(trainX, trainY, epochs=EPOCHS, batch_size=32,
                            validation_data=(testX, testY), callbacks=callbacks_list,
                            verbose=1)

        acc = model.evaluate(testX, testY, verbose=0)
        #for i in range(len(acc)):
        print(f'Accuracy: {round(acc[1] * 100,2)} %')
        final_fit = True

    return


def upload_data(path, minio_cl, logger, stop_thread):
    while not stop_thread.is_set():
        try:
            sleep(20)
            minio_c.upload_directory(bucket_name=f"{CI_BUCKET}",
                                          directory_name="",
                                          source_dir=path,
                                          minio=minio_cl,
                                          logger=logger,
                                          force=True)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(str(e))
            print("No data to upload yet, try again.")
    return


# summarize model performance
def summarize_performance(acc):
    # Print summary
    print(f'Accuracy: {round(acc[1] * 100,2)} %')


# run the test harness for evaluating a model
def run_test_harness(local_path, logger, minio_client):
    global final_fit, history, accuracy

    stop_thread = threading.Event()

    # load dataset
    trainX, trainY, testX, testY = load_dataset()
    # prepare pixel data
    trainX, testX = prep_pixels(trainX, testX)

    minio_thread = threading.Thread(name='minio', target=upload_data,
                                    args=(local_path, minio_client, logger, stop_thread))
    multiprocessing.set_start_method("fork")
    training_process = multiprocessing.Process(target=evaluate_model,
                                               args=(trainX, trainY, testX, testY,
                                                     local_path, trained_epochs))

    signal.signal(signal.SIGTERM, sigterm_handler)

    try:
        minio_thread.start()
        f = open('checkpoint/out.txt', 'w')
        sys.stdout = log_console_output(sys.stdout, f)
        training_process.start()

        training_process.join()
        stop_thread.set()
        minio_thread.join()

        endpoint_env = "KRAKE_COMPLETE_URL"
        token_env = "KRAKE_COMPLETE_TOKEN"
        default_ca_bundle = "/etc/krake_complete_cert/ca-bundle.pem"
        default_cert_path = "/etc/krake_complete_cert/cert.pem"
        default_key_path = "/etc/krake_complete_cert/key.pem"

        cert_and_key = None
        ca = False
        # Only set if TLS is enabled. Otherwise the files do not exist.
        if os.path.isfile(default_cert_path) and os.path.isfile(default_key_path):
            cert_and_key = (default_cert_path, default_key_path)
            ca = default_ca_bundle

        endpoint = os.getenv(endpoint_env)
        token = os.getenv(token_env)

        print(endpoint, flush=True)
        print(token, flush=True)

        response = requests.put(
            endpoint, verify=ca, json={"token": token}, cert=cert_and_key
        )
        assert response.status_code == 200, f"Error in response: {response.text}"

        # summarize estimated performance
        # summarize_performance(accuracy)
    except ExitSignal:
        training_process.terminate()
        stop_thread.set()
        minio_thread.join()
        pass


# entry point, run the test harness
if __name__ == "__main__":
    run_test_harness(local_path=local_filepath, logger=logger, minio_client=minio_client)
