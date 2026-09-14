"""Cross-process file lock for local JSON read/modify/write transactions."""
from contextlib import contextmanager
import os
from pathlib import Path
import time


@contextmanager
def file_lock(path, timeout=15):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'\0'); stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'Conversation storage is busy: {path}')
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


# Share nesting state across memory objects targeting the same directory.
import threading

_states_guard = threading.Lock()
_states = {}


class StorageLock:
    """Thread-reentrant lock backed by an OS lock shared by other processes."""
    def __init__(self, path, timeout=15):
        self.path = Path(path).resolve()
        self.timeout = timeout
        key = os.path.normcase(str(self.path))
        with _states_guard:
            self._mutex, self._local = _states.setdefault(key, (threading.RLock(), threading.local()))

    def __enter__(self):
        if not self._mutex.acquire(timeout=self.timeout):
            raise TimeoutError(f"Conversation storage is busy: {self.path}")
        try:
            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                context = file_lock(self.path, timeout=self.timeout)
                context.__enter__()
                self._local.context = context
            self._local.depth = depth + 1
            return self
        except BaseException:
            self._mutex.release()
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self._local.depth -= 1
            if self._local.depth == 0:
                context = self._local.context
                del self._local.context
                context.__exit__(exc_type, exc_value, traceback)
        finally:
            self._mutex.release()
