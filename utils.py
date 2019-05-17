import threading


def threaded(func):
    def threaded_func(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.start()
    return threaded_func