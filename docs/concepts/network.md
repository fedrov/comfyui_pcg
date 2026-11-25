# Network feedback

What Houdini's network view tells you about cooking, on the ComfyUI canvas.

## On the nodes

After a run, every node that ran shows, right of its title bar:

| Mark | Means |
|---|---|
| `12 ms` | How long the node took (its own work; a node that comes from ComfyUI's cache shows its last time and *(cached)*). |
| Red **!** | The node failed. |
| Yellow **!** | The node ran with warnings. |
| Amber dot, dimmed time | Out of date: one of its parameters, wires or its bypass state changed since it last ran, or something upstream of it did. |

The times can be hidden with the PCG setting *Show the cook time above each node*.

## Node info (middle button)

Press the middle mouse button on a node without moving it: its info opens next to the pointer.

- how long it took, or that it came from the cache, failed, or is out of date
- for geometry: point, primitive and vertex counts, memory, bounding box and size, the attributes by class (point, vertex, primitive, detail) with their type and size (`f3` = 3 floats), the point and primitive groups
- for a COP image: its resolution and layers with their channel counts
- its warnings, or its error message (with what its last good result was)
- notes on how its time was spent, where a node gives them (Geometry Preview's Outdoor look: the frame size, CPU or GPU, and the seconds per stage)

It stays open until the next click or Esc. Dragging with the middle button still pans the canvas and shows nothing. Nodes cached by the server since before you reloaded the page still show what they reported when they last ran.

## Performance pane

The **Performance** tab on the window's right edge opens the last run node by node, slowest first, with a bar per node, its total time and how many nodes came from the cache. Failed nodes are red, nodes with warnings yellow. Click a row to select the node and bring it to the middle of the canvas. *Every node* adds the nodes of other packs (their time is measured from the order the server ran them in). The pane can be moved and resized; ✕ hides it again.
