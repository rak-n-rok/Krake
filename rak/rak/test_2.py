import logging
import time
import concurrent.futures


def thread_function(my_value):
    try:
        # logging.info("Thread %s: starting", name)
        logging.info("Thread: starting")
        print(my_value)
        my_value = 1
        time.sleep(2)
        print(my_value)
        # logging.info("Thread %s: finishing", name)
        logging.info("Thread: finishing")
    except Exception as e:
        print("Got Exception")
        print(e)


# if __name__ == "__main__":
#     format = "%(asctime)s: %(message)s"
#     logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
#     logging.info("Main    : before creating thread")
#     x = threading.Thread(target=thread_function, args=(1,), daemon=True)
#     logging.info("Main    : before running thread")
#     x.start()
#     logging.info("Main    : wait for the thread to finish")
#     # x.join()
#     logging.info("Main    : all done")


if __name__ == "__main__":
    format = "%(asctime)s: %(message)s"
    logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")

    value = 0
    print(value)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        executor.submit(thread_function, value)

    print(value)
