// comfyui_pcg/web/pcg_foreach.js
//
// Two small things:
//
// 1) Hide input ports whose names start with an underscore.
//    For-Each's _state / _accum are internal state that Block End **injects as literals** when it expands
//    the subgraph; they only exist on the server. But they must be declared in INPUT_TYPES --
//    ComfyUI's get_input_data only passes "declared" inputs to the node function; undeclared ones are
//    dropped entirely. Declaring them grows ports, so the frontend removes them.
//
//    This is done by deleting them from nodeData in beforeRegisterNodeDef, rather than waiting until the node
//    is built and calling removeInput: the latter shifts the inputs array indices and links get misaligned when a workflow is restored.
//
//    This is a general rule that applies to all PCG_ nodes -- if a node later needs to hide an internal input,
//    just prefix its name with an underscore; no need to come back to this file.
//
// 2) Give the loop link its own color. The Block Begin -> Block End link is the loop's
//    skeleton rather than data flow; mixed in with geometry links it is hard to see the block's extent at a glance.

import { app } from "../../scripts/app.js";

const LOOP_COLOR = "#f0a63c";
const ACC_COLOR = "#6b7280";

app.registerExtension({
  name: "pcg.foreach",

  init() {
    // link_type_colors lives in different places in different frontend versions; try them all, failure does not affect functionality
    const targets = [
      globalThis.LGraphCanvas?.link_type_colors,
      app.canvas?.default_connection_color_byType,
      app.canvas?.default_connection_color_byTypeOff,
    ];
    for (const t of targets) {
      if (!t) continue;
      t["PCG_LOOP"] = LOOP_COLOR;
      t["PCG_LOOPACC"] = ACC_COLOR;
    }
  },

  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!nodeData?.name?.startsWith("PCG_")) return;
    for (const bucket of ["required", "optional"]) {
      const d = nodeData.input?.[bucket];
      if (!d) continue;
      for (const key of Object.keys(d)) {
        if (key.startsWith("_")) delete d[key];
      }
    }
  },

  // Give the two loop-block nodes an identifying color so the block's extent stands out on the canvas
  nodeCreated(node) {
    const t = node.comfyClass || node.constructor?.comfyClass;
    if (t === "PCG_ForEachBegin" || t === "PCG_ForEachEnd") {
      node.color = "#3a2f1a";
      node.bgcolor = "#4a3c20";
    }
  },
});
