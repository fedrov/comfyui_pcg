"""
Progress and interruption for long-running nodes (pcg126).

An erosion pass or a lit render takes a minute or more; without this ComfyUI shows a node that neither moves its
progress bar nor reacts to Cancel until it is done. `Progress(total)` is the one thing a loop needs:

    prog = Progress(iterations)
    for step in range(iterations):
        ...
        prog.step()

Each step advances the node's progress bar (ComfyUI's `comfy.utils.ProgressBar`, throttled to about a hundred updates
so a 100 000-step loop does not flood the websocket) and asks ComfyUI whether the user pressed Cancel
(`comfy.model_management.throw_exception_if_processing_interrupted`), which raises ComfyUI's own interruption
exception: the queue stops exactly as it does for a sampler.

Outside ComfyUI (tests, scripts) there is no `comfy` package and everything here is a no-op. The geometry code never
imports ComfyUI itself: this module is the only place that looks for it, lazily and once.

`sink` is for tests and tools: a callable (done, total) that receives every throttled update, and may raise to
simulate a cancel.
"""
from __future__ import annotations

_comfy = None            # (ProgressBar class or None, interrupt check or None) once resolved
sink = None              # optional callable(done, total), see above


def _resolve():
    global _comfy
    if _comfy is None:
        bar = chk = None
        try:
            import comfy.utils as _u
            bar = getattr(_u, "ProgressBar", None)
        except Exception:
            pass
        try:
            import comfy.model_management as _mm
            chk = getattr(_mm, "throw_exception_if_processing_interrupted", None)
        except Exception:
            pass
        _comfy = (bar, chk)
    return _comfy


def check():
    """Raise ComfyUI's interruption exception if the user cancelled; nothing otherwise."""
    chk = _resolve()[1]
    if chk is not None:
        chk()


class Progress:
    """Progress over `total` steps. step(n) advances; the bar and the cancel check run at most ~100 times."""

    def __init__(self, total, updates=100):
        self.total = max(int(total), 1)
        self.done = 0
        self._every = max(1, self.total // max(int(updates), 1))
        self._sent = 0
        bar, self._chk = _resolve()
        self._bar = None
        if bar is not None:
            try:
                self._bar = bar(self.total)
            except Exception:
                self._bar = None

    def step(self, n=1):
        self.done = min(self.done + int(n), self.total)
        if self.done - self._sent < self._every and self.done < self.total:
            return
        delta, self._sent = self.done - self._sent, self.done
        if self._chk is not None:
            self._chk()
        if sink is not None:
            sink(self.done, self.total)
        if self._bar is not None and delta > 0:
            try:
                self._bar.update(delta)
            except Exception:
                pass
