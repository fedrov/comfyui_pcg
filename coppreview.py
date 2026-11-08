"""
Thumbnails inside COP nodes -- like Substance Designer: **every node carries a preview**.

In a chain like COP this is not a nice-to-have. When a geometry chain goes wrong, plugging in a Viewport for a look
is enough, because geometry is 3D and one viewport shows it all; but an image chain is a dozen nodes in a row
modifying the same image, and "which step starts going wrong" can only be located by **seeing every step at once**. Substance
Designer, Nuke and Houdini's COP view all do this; it is no coincidence.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Send **raw floats**, not PNG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The easiest approach is to encode a PNG on the server and send it. That is not done here, because COP layers **are not
in 0-1 to begin with**: SDFs are signed, heightfields are in metres, normals are ±1. Encoding to PNG forces choosing a value-range
mapping on the spot, and choosing wrong (an SDF clamped to all black) happens exactly when you most need to see clearly.

So the downsampled **float32 raw values** are sent, and the clamp / signed / normalize mapping happens in the frontend:

    · switching mapping mode needs no recompute of the whole chain -- that is where the Substance-style immediacy comes from
    · hovering reads the **real pixel value** directly, not a mapped 0-255
    · all layers are sent at once, so switching C / mask / sdf needs no recompute either

The cost is bytes: 192² single-channel is 147 KB, four channels 590 KB. So by default it downsamples to 192 and only sends
the first 8 layers -- this is localhost, a few hundred KB do not matter, but there is no need to send a 2048² original either.

Downsampling uses `filters.resize`, which is backend-neutral: if the image is in VRAM it is **shrunk on the GPU**,
and only the shrunk small image crosses PCIe once.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No node code is changed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`attach_cop_preview` scans the node table and wraps every node that outputs COPIMAGE: it adds
`hidden.unique_id`, puts the output into the cache after execution, and adds `ui.pcg_cop` to the return value.

Same approach as `groups_report.py`, for the same reason: COP nodes added later get a preview
automatically, without anyone remembering "don't forget those three lines". Forgetting would **silently** lose a thumbnail -- silent failures are
the hardest kind to notice.

The wrapping is idempotent (marked), and it stacks with the groups_report wrapping -- both merge into
the `ui` dict without overwriting each other.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Binary format
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    [4B magic "PCGC"][4B header length][JSON header (space-padded to 4-byte alignment)][float32 data]

The header must be padded to **4-byte alignment**, otherwise the frontend's `new Float32Array(buf, offset)` throws
right away because byteOffset is misaligned -- viewport.py already fell into this pit once; this copies
its fix.

Row order is COP-native **v up (row 0 is the bottom)**; the frontend writes rows in reverse when drawing. Flipping once
in the browser is cheaper than copying a whole block of memory in Python, and the flip still only happens at the "Python <->
outside world" boundary.
"""
from __future__ import annotations

import json
import struct
import threading

import numpy as np

from .geo.cop import CopImage, filters as _cflt, bridge as _cbrg

MAGIC = b"PCGC"
PREVIEW_MAX = 192          # longest side of the thumbnail
MAX_LAYERS = 8             # max number of layers sent
_MARK = "_pcg_cop_preview"

_CACHE: dict = {}
_REV = [0]
_LOCK = threading.Lock()


def _fit(img):
    """Downsample so the longest side is within PREVIEW_MAX. Returned as is if already small enough."""
    x, y = img.res
    m = max(x, y)
    if m <= PREVIEW_MAX:
        return img
    k = PREVIEW_MAX / float(m)
    return _cflt.resize(img, max(1, int(round(x * k))),
                        max(1, int(round(y * k))))


def encode(img):
    """CopImage -> binary block for the preview."""
    small = _fit(img)
    layers, buffers = [], []
    for name in small.names[:MAX_LAYERS]:
        a = _cbrg.to_preview_float(small, name, flip=False)
        lo = float(np.min(a)) if a.size else 0.0
        hi = float(np.max(a)) if a.size else 0.0
        layers.append({"name": name, "w": int(a.shape[1]),
                       "h": int(a.shape[0]), "c": int(a.shape[2]),
                       "min": lo, "max": hi,
                       "bytes": int(a.nbytes)})
        buffers.append(a.tobytes())
    header = {"v": 1, "xres": img.xres, "yres": img.yres,
              "device": img.device, "layers": layers,
              "full": [img.xres, img.yres]}
    hj = json.dumps(header).encode("utf-8")
    # pad with spaces to 4-byte alignment -- otherwise the frontend's new Float32Array(buf, offset) throws
    hj += b" " * ((-(8 + len(hj))) % 4)
    return MAGIC + struct.pack("<I", len(hj)) + hj + b"".join(buffers)


def publish(node_id, img):
    """Store in the cache and return the metadata for the frontend (no pixels)."""
    if node_id is None or img is None or len(img) == 0:
        return None
    with _LOCK:
        _REV[0] += 1
        rev = _REV[0]
        _CACHE[str(node_id)] = (rev, encode(img))
    return {"node_id": str(node_id), "rev": rev,
            "xres": img.xres, "yres": img.yres,
            "device": img.device, "layers": img.names}


def _takes_cop(cls):
    """Whether this node takes COPIMAGE as input."""
    try:
        spec = cls.INPUT_TYPES()
    except Exception:
        return False
    for group in ("required", "optional"):
        for v in (spec.get(group) or {}).values():
            if isinstance(v, (tuple, list)) and v and v[0] == "COPIMAGE":
                return True
    return False


def _first_cop(value):
    if isinstance(value, CopImage):
        return value
    if isinstance(value, (tuple, list)):
        for v in value:
            got = _first_cop(v)
            if got is not None:
                return got
    return None


# ------------------------------------------------------------ HTTP routes
def _register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return False                      # silently skip when unit-testing outside ComfyUI

    @PromptServer.instance.routes.get("/pcg/cop/{node_id}")
    async def _pcg_cop(request):
        nid = request.match_info["node_id"]
        with _LOCK:
            item = _CACHE.get(nid)
        if item is None:
            return web.Response(status=404, text="no cop preview for " + nid)
        return web.Response(body=item[1],
                            content_type="application/octet-stream",
                            headers={"Cache-Control": "no-store",
                                     "X-PCG-Rev": str(item[0])})
    return True


_ROUTES_OK = _register_routes()


# ------------------------------------------------------------ wrapping
def attach_cop_preview(mappings):
    """
    Attach previews to every node that outputs COPIMAGE. Idempotent.

    Does two things: adds `hidden.unique_id` to `INPUT_TYPES` (without it there is no
    node id at execution time, so the cache has no key), and wraps the execution function.
    """
    for cls in mappings.values():
        rt = tuple(getattr(cls, "RETURN_TYPES", ()) or ())
        # Nodes that output COPIMAGE preview their own output; nodes that only **take** COPIMAGE (COP Export,
        # COP Info) preview their input -- otherwise those two nodes would be bare, and they are exactly
        # where "what did I actually get" matters most
        takes = _takes_cop(cls)
        if "COPIMAGE" not in rt and not takes:
            continue
        fn_name = getattr(cls, "FUNCTION", None)
        fn = getattr(cls, fn_name, None) if fn_name else None
        if fn is None or getattr(fn, _MARK, False):
            continue

        orig_inputs = cls.INPUT_TYPES

        # Did this node **originally** want unique_id? That decides whether the preview should swallow it.
        #
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # This once caused a very expensive bug: the wrapped below unconditionally did
        # `kwargs.pop("unique_id")`, **taking the node id out of the arguments** before calling the original function.
        # For nodes that never wanted a node id and only got a hidden one forced on by the preview layer,
        # that is correct. But `PCG_ForEachFrameEnd` has a cop input, so it gets wrapped by this
        # layer -- and it **needs** unique_id **itself** (to locate the end node of the loop body).
        # Once it was stolen, it received None, so `expand_body(str(None), ...)` looked in the graph
        # for a node called 'None' and raised `KeyError: no node 'None' in the graph`.
        # In other words **For-Each Frame Block was entirely broken in real ComfyUI**.
        #
        # Why it went unnoticed for so long: comfyui_pcg/__init__.py in the dev sandbox was a stub
        # that bypassed the attach_cop_preview / attach_group_reporting layers,
        # so the whole test suite ran **unwrapped** nodes -- that layer was never tested.
        # It only blew up after laying things out exactly as on the real install.
        #
        # The criterion is clean: only a unique_id **added by the preview layer itself** belongs to the preview layer;
        # anything the node declared itself is passed through unchanged.
        try:
            _orig_hidden = (orig_inputs() or {}).get("hidden") or {}
        except Exception:
            _orig_hidden = {}
        steal_uid = "unique_id" not in _orig_hidden

        def make_inputs(orig):
            # The signature must accept cls: it is wrapped in classmethod outside and passed in on call.
            # orig is a method **already bound** to the class, so plain orig() works
            def wrapped_inputs(_cls):
                spec = orig()
                h = dict(spec.get("hidden") or {})
                h.setdefault("unique_id", "UNIQUE_ID")
                return {**spec, "hidden": h}
            wrapped_inputs.__dict__[_MARK] = True
            return classmethod(wrapped_inputs)

        if not getattr(orig_inputs.__func__ if hasattr(orig_inputs, "__func__")
                       else orig_inputs, _MARK, False):
            cls.INPUT_TYPES = make_inputs(orig_inputs)
        if steal_uid:
            # Record "this hidden was inserted by the preview layer, not declared by the node itself".
            # The test checking run() signatures uses it to subtract -- otherwise it would report
            # "the original function has no unique_id parameter" as a missing parameter, when that is actually correct.
            cls._pcg_injected_hidden = tuple(sorted(
                set(getattr(cls, "_pcg_injected_hidden", ())) | {"unique_id"}))

        def make(orig, steal=steal_uid):
            def wrapped(self, *args, **kwargs):
                # nodes with steal=False use unique_id themselves; it may only be read, not taken
                nid = (kwargs.pop("unique_id", None) if steal
                       else kwargs.get("unique_id"))
                out = orig(self, *args, **kwargs)
                res = out.get("result") if isinstance(out, dict) else out
                # look at the outputs first, fall back to the inputs if none -- COP Export / COP Info take the latter path
                img = _first_cop(res)
                if img is None:
                    img = _first_cop(args) or _first_cop(
                        tuple(kwargs.values()))
                meta = None
                try:
                    meta = publish(nid, img)
                except Exception as ex:
                    # a broken preview must never take down the render -- log one line and move on
                    print(f"[PCG COP preview] {type(ex).__name__}: {ex}")
                if meta is None:
                    return out
                payload = {"pcg_cop": [meta]}
                if isinstance(out, dict):
                    return {**out, "ui": {**(out.get("ui") or {}), **payload}}
                return {"ui": payload, "result": out}
            wrapped.__dict__.update(getattr(orig, "__dict__", {}))   # carry out the markers of the inner layers
            setattr(wrapped, _MARK, True)
            # same as groups_report: let inspect.signature see through this layer
            wrapped.__wrapped__ = orig
            wrapped.__name__ = getattr(orig, "__name__", "run")
            wrapped.__doc__ = getattr(orig, "__doc__", None)
            return wrapped

        setattr(cls, fn_name, make(fn))
    return mappings
