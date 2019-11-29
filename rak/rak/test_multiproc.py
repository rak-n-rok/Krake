from multiprocessing import Pool
from time import sleep

import sys


def my_sleep(x):
    print("Hello")
    sleep(x)
    print("Goodbye")
    return x


def f(x, y):
    print("Hello")
    sleep(1)
    print("Goodbye")
    try:
        return x / y
    except ZeroDivisionError as e:
        print(e)
        raise e


def my_map(
    pool, func, iterable=None, chunksize=None, callback=None, error_callback=None
):

    results = [
        pool.apply_async(
            func, args=args, callback=callback, error_callback=error_callback
        )
        for args in iterable
    ]

    pool.join()  # Wait for all tasks to finish

    return results


if __name__ == "__main__":
    #     with Pool(5) as p:
    #         stack_outputs = p.starmap(f, [[1, 2], [3, 0], [2, 3]])
    #
    #     print(stack_outputs)

    with Pool(2) as p:
        results = [p.apply_async(f, args=args) for args in [[1, 2], [3, 0], [2, 3]]]
        p.close()
        p.join()

    for result in results:
        if result.successful():
            print(result.get())
        else:
            print("Not successful")

    sys.exit(0)

    with Pool(2) as p:
        # p = Pool(2)
        # it_x = p.imap(f, [[1, 2], [3, 1], [2, 3]])
        it_x = p.imap(f, [1])
        #
        #         res = None
        #         print(x.get())
        #         res = x.get()
        #         try:
        #             x.successful()
        #         except AssertionError:
        #             pass
        #         else:
        #             res = x.get()

        p.close()
        p.join()

    for x in it_x:
        print(x)

    sys.exit(0)

    with Pool(2) as p:
        # p = Pool(2)
        x = p.starmap_async(f, [[1, 2], [3, 0], [2, 3]])
        # x = p.starmap_async(my_sleep, [4, 3, 2, 1])
        # it_x = p.starmap_async(sleep, [4, 3, 2, 1])

        res = None
        print(x.get())
        res = x.get()
        #         try:
        #             x.successful()
        #         except AssertionError:
        #             pass
        #         else:
        #             res = x.get()

        p.close()
        p.join()

    print(res)


#    print(x)
