"""comfyui_pcg -- Houdini-style procedural geometry nodes for ComfyUI."""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from . import viewport as _vp
from . import spreadsheet as _ss
from . import expr as _ex
from . import params as _pm
from . import foreach as _fe
from . import framefor as _ff
from .groups_report import attach_group_reporting
from .coppreview import attach_cop_preview

for _m in (_vp, _ss, _ex, _pm, _fe, _ff):
    NODE_CLASS_MAPPINGS.update(_m.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_m.NODE_DISPLAY_NAME_MAPPINGS)

# Packed primitives (pcg121): nodes that don't handle them get their geometry inputs unpacked automatically.
# Wrapped first (innermost), so the other wrappers see the real result. See geo/packed.py
from .geo.packed import attach_auto_unpack
attach_auto_unpack(NODE_CLASS_MAPPINGS)

# Every node that outputs geometry also reports "which groups I have" to the frontend,
# so the frontend can list the choices on downstream group parameters. See groups_report.py
attach_group_reporting(NODE_CLASS_MAPPINGS)

# Nodes that output geometry also send a summary and a key in ui; queries in parameter fields such as npoints("../box1"),
# point("../box1", 0, "P", 1) rely on it. See geoquery.py
from .geoquery import attach_geo_query
attach_geo_query(NODE_CLASS_MAPPINGS)

# Every COP node gets a thumbnail inside its body (Substance Designer style). Also a wrapper layer,
# so newly added COP nodes get it automatically -- forgetting to add it would **silently** lose a thumbnail. See coppreview.py
attach_cop_preview(NODE_CLASS_MAPPINGS)

# Parameter panel layout info (labels, tabs, vectors on one row, hidewhen ...) goes into each input's options,
# reaches the frontend via /object_info, and web/pcg_panel.js draws it as a Houdini-style panel. See panel.py
from .panel import attach_panels
attach_panels(NODE_CLASS_MAPPINGS)

# After a node that ran for more than a quarter of a second, freed memory goes back to the OS (glibc keeps it otherwise,
# and ComfyUI's cache of every output piles the slack up). Outermost layer. See memtrim.py
from .memtrim import attach_memtrim
attach_memtrim(NODE_CLASS_MAPPINGS)

# Frontend assets directory. ComfyUI mounts it at /extensions/<package name>/
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
