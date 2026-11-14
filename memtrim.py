"""
Give freed memory back to the operating system after a long node (glibc only; a no-op elsewhere).

Measured on the open-world tiles example: a 4096² COP Wrangle run in bands of rows allocates and frees thousands of
4 MB blocks. glibc raises its mmap threshold after the first such free, so the later blocks come from the heap, and the
freed heap stays with the process: the node's result was 384 MB, the process grew by 1.77 GB, and malloc_trim(0)
gave 1.65 GB of it back. ComfyUI keeps every node's output, so that slack piled up node after node until a machine
with 8 GB ran out. Trimming takes milliseconds; it runs only after a node that took more than a quarter of a second.

After a node that took more than a few seconds the garbage collector runs first: arrays held only by reference cycles
(closures, frames kept by tracebacks) wait for Python's rare full collection otherwise, and on the open-world example
2 GB of them were still held when the preview render started (the test process ran out of memory there).
"""
import gc
import ctypes
import sys
import time

_MARK = "_pcg_memtrim"
_THRESHOLD_S = 0.25
_COLLECT_S = 3.0
_trim = None
if sys.platform.startswith("linux"):
    try:
        _trim = ctypes.CDLL("libc.so.6").malloc_trim
        _trim.argtypes = [ctypes.c_size_t]
        _trim.restype = ctypes.c_int
    except (OSError, AttributeError):        # musl and other libcs have no malloc_trim
        _trim = None


def trim(collect=False):
    """Return free heap pages to the OS (after a full garbage collection if collect). True if the call was made."""
    if collect:
        gc.collect()
    if _trim is None:
        return False
    try:
        _trim(0)
    except Exception:
        return False
    return True


def attach_memtrim(mappings):
    for cls in mappings.values():
        fn_name = getattr(cls, "FUNCTION", None)
        fn = getattr(cls, fn_name, None) if fn_name else None
        if fn is None or getattr(fn, _MARK, False):
            continue

        def make(orig):
            def wrapped(self, *args, **kwargs):
                t = time.perf_counter()
                try:
                    return orig(self, *args, **kwargs)
                finally:
                    dt = time.perf_counter() - t
                    if dt > _THRESHOLD_S:
                        trim(collect=dt > _COLLECT_S)
            wrapped.__dict__.update(getattr(orig, "__dict__", {}))
            setattr(wrapped, _MARK, True)
            wrapped.__wrapped__ = orig
            wrapped.__name__ = getattr(orig, "__name__", "run")
            wrapped.__doc__ = getattr(orig, "__doc__", None)
            return wrapped
        setattr(cls, fn_name, make(fn))
