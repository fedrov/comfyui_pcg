"""
Install self-check. Running it inside ComfyUI is inconvenient, so it is a standalone script:
    python examples/check_install.py
prints the status of every dependency and every module item by item, so a broken step is obvious at a glance.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

OK, FAIL = "  [ok]  ", "  [FAIL]"
errors = 0


def check(label, fn, required=True):
    global errors
    try:
        info = fn()
        print(f"{OK} {label}" + (f"  -> {info}" if info else ""))
    except Exception as e:
        if required:
            errors += 1
            print(f"{FAIL} {label}  -> {type(e).__name__}: {e}")
        else:
            print(f"  [skip] {label}  -> not installed ({e.__class__.__name__}), optional")


print(f"\npython {sys.version.split()[0]}  @  {sys.executable}\n")
print("-- dependencies --")
check("numpy", lambda: __import__("numpy").__version__)
check("trimesh (glb/obj import/export)", lambda: __import__("trimesh").__version__, False)
check("PIL (demo saves png)", lambda: __import__("PIL").__version__, False)
check("torch (PreviewImage node)", lambda: __import__("torch").__version__, False)

print("\n-- geometry layer --")
check("geo.core", lambda: __import__("comfyui_pcg.geo.core", fromlist=["x"]) and "")
check("geo.build", lambda: __import__("comfyui_pcg.geo.build", fromlist=["x"]) and "")
check("geo.ops", lambda: __import__("comfyui_pcg.geo.ops", fromlist=["x"]) and "")
check("geo.wrangle", lambda: __import__("comfyui_pcg.geo.wrangle", fromlist=["x"]) and "")
check("geo.convert", lambda: __import__("comfyui_pcg.geo.convert", fromlist=["x"]) and "")


def pipeline():
    from comfyui_pcg.geo import build, ops, wrangle, convert
    g = build.grid(10, 10, 25, 25)
    g = wrangle.run_wrangle(g, "@P.y = sin(length(@P))")
    g = ops.compute_normals(g)
    p = ops.scatter(g, 50, seed=1)
    c = ops.copy_to_points(build.box((.2, .2, .2)), p)
    m = ops.merge(g, c)
    img = convert.render_preview(m, 64, 64)
    assert img.max() > 0, "software rasterizer rendered all black, check convert.render_preview"
    return f"{m.npoints} pts / {m.nprims} prims, render OK"


check("full chain grid->wrangle->normal->scatter->copy->merge->render", pipeline)


def encode():
    from comfyui_pcg.geo import build
    from comfyui_pcg import viewport
    blob = viewport.encode(build.sphere())
    return f"{len(blob)} bytes"


check("viewport binary encoding", encode)

print("\n-- frontend assets --")
web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
check("web/pcg_viewport.js", lambda: os.path.getsize(
    os.path.join(web, "pcg_viewport.js")) and "present")
v = os.path.join(web, "vendor", "three.module.js")
print(f"{OK} web/vendor/three.module.js  -> in place" if os.path.exists(v)
      else "  [warn] web/vendor/three.module.js not in place, viewport will try the CDN")

print("\n" + ("All passed." if errors == 0 else f"{errors} item(s) failed, see [FAIL] above."))
sys.exit(1 if errors else 0)
