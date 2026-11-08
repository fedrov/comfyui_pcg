"""
Verify that the geometry layer works, directly, without starting ComfyUI.
    python examples/demo.py
Produces demo_preview.png and demo_mesh.obj.

This script is also an API usage example for the geo/ layer -- ComfyUI nodes do exactly what is done here,
they just take the parameters from widgets.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from comfyui_pcg.geo import build, ops, wrangle, convert, POINT, PRIM   # noqa: E402


def main():
    # 1) Grid SOP: 40x40 units, 65x65 points
    terrain = build.grid(size_x=40, size_z=40, cols=65, rows=65)
    print("[grid]      ", terrain)

    # 2) Point Wrangle: two layers of sines as terrain, also writing Cd and a slope attribute
    terrain = wrangle.run_wrangle(terrain, """
h  = sin(@P[:,0]*0.25) * cos(@P[:,2]*0.2) * 3.0
h += sin(@P[:,0]*0.9 + 1.3) * 0.6
@P.y = h
@height = h
@Cd = np.stack([fit(h,-4,4,0.15,0.85), np.full(@numpt,0.45), np.full(@numpt,0.3)], 1)
""")
    print("[wrangle]   ", terrain.names(POINT))

    # 3) Normal SOP
    terrain = ops.compute_normals(terrain, "point")

    # 4) Group + Blast: cut away low-lying areas (turning height into a group takes a wrangle writing a mask)
    lowmask = terrain.get(POINT, "height")[:, 0] < -2.5
    terrain_cut = ops.delete_points(terrain, ~lowmask) if lowmask.any() else terrain
    print("[blast]      low-lying points =", int(lowmask.sum()))

    # 5) Scatter: scatter 400 points weighted by area, inheriting N / Cd / height
    pts = ops.scatter(terrain, count=400, seed=12)
    print("[scatter]   ", pts, pts.names(POINT))

    # 6) Write a random pscale on each scattered point; it takes effect in Copy to Points
    rng = np.random.default_rng(3)
    pts.set(POINT, "pscale", rng.uniform(0.5, 1.4, pts.npoints).astype(np.float32))

    # 7) Copy to Points: a tapered tube as a "tree", +Z aligned to the point normal
    tree = build.tube(radius1=0.25, radius2=0.02, height=2.5, cols=6, rows=2, caps=True)
    tree = ops.transform(tree, translate=(0, 0, 1.25), rotate=(90, 0, 0))   # +Y -> +Z, so aligning +Z to N when copying makes it "stand up"
    forest = ops.copy_to_points(tree, pts, up=(0, 1, 0))
    print("[copy]      ", forest)

    # 8) Merge
    scene = ops.merge(terrain, forest)
    print("[merge]     ", scene)
    print()
    print(scene.info())

    # 9) Output
    here = os.path.dirname(os.path.abspath(__file__))
    img = convert.render_preview(scene, 640, 640, elev=22, azim=40, shade="lambert")
    try:
        from PIL import Image
        Image.fromarray((img * 255).astype(np.uint8)).save(
            os.path.join(here, "demo_preview.png"))
        print("\nwrote demo_preview.png")
    except ImportError:
        np.save(os.path.join(here, "demo_preview.npy"), img)

    convert.write_obj(scene, os.path.join(here, "demo_mesh.obj"))
    print("wrote demo_mesh.obj")


if __name__ == "__main__":
    main()
