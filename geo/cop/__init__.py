"""
COP -- Copernicus. Mirrors Houdini 20.5's image context.

    core        CopImage data model (named layers, v up, linear float32, unclamped)
    generate    constant / noise / shapes (SDF) / ramps
    filters     resampling / bilinear sampling / Gaussian blur
    transform   translate-rotate-scale / flip / crop / tile / warp by vector field
    levels      Levels / Remap / Clamp / Quantize / Invert / Fit / luminance
    morph       erode-dilate-open-close / edge detect / sharpen / median
    sdf         mask -> signed distance field (exact EDT + JFA)
    composite   blend modes + Porter-Duff over
    bridge      interop with ComfyUI IMAGE / MASK
    control     pack into IMAGE / MASK following ControlNet conventions (semantic conversion layer)
    heightmap   height ↔ normal / AO / shadow / caustics / refraction, normal blending and conversion
    erosion     erosion filters (stateless, per-pixel, not a simulation)
    analysis    slope / curvature / statistics / histogram / connected segmentation / image compare
    terrain     mask by feature / terrace / thermal erosion / height field to mesh
    flow        fill sinks / flow direction / flow accumulation / river network / fluvial erosion (stream power)
    splat       terrain -> a set of material masks summing to 1 (splat map)
    regions     the mask part of regional prompts (parsing / layered compositing / preview)
    lift        depth map / MoGe points -> top-down height field
    hydro       hydraulic erosion (droplet scouring + transport + deposition)
    pixel       per-pixel: colour correction / channels / vectors / functions / logic / keying / layer management / Wrangle ...
    fx          filters / effects / distortion: depth of field, directional blur, convolution, TV denoise, glow, drop shadow, lens distortion, corners, hole filling ...
    pattern     patterns: checker / brick / cells / UV grid / Julia / Chladni / knit / weave, plus text
    noisex      five more noise types: bubble / crystal / phasor / curl / cloud
    stamp       scatter shapes / stamp / autostereogram, plus the geometry ↔ image coordinate convention
    solve       FFT / prefix sums / Poisson / eikonal equation / segment by value / bounding rectangle / compare blend
    sim         reaction-diffusion / Turing / water ripples / 2D fluid / FFT ocean
    uvx         UV Map / sample / transform / invert, polar coordinates, Hex Tile, Triplanar, Retile, SDF operations, ID conversion
    geoimg      geometry ↔ image: image to points, blobs to points, curve rasterization, Gaussian splat rasterization, texture baking
    hfvis       lighting, height field crop / project / strata, visualization, tile mosaic, transitions, sequence operators
    sdf2d       extra 2D distance functions for SDF Shape (polygon / egg / moon / cross / arch / arrow ...)
    uvshape     UV Shape: parametric coordinates of disk / ring (pairs with UV Sample)
    coordspace  Copernicus coordinate spaces (Texture / Image / Pixel / World), Border·Shift·Cycles,
                polar coordinate conversion, Space Transform, Position Map
    geolayer    geometry ↔ layer with Houdini semantics (pcg100 c8): Point Generate ...
    warp3d      Sphere Sample, Transform 3D (Rasterize), Align / Align Pixels, Bend, sampling with Filter
    filtersim   pcg100 c7: Feather (max slope) with Houdini semantics, Extrapolate Boundaries, Edge Detect
                by Contour / Depth / Normal, Surface Dither, Turing Patterns, Heat Distort by Layer
    colorkey    Despill / Equalize / Histogram (drawing) / Compare (mask) / Mono to RGB / Mono to HeightField with Houdini semantics
    accel       compute engine for heavy iterative nodes: numpy / torch float64 (CUDA on large images when Compute = auto)

Flipping v only happens at the **exits**: the bridge and control files. Anywhere else it is a bug.
"""
from __future__ import annotations

from .core import (CopImage, DEFAULT_LAYER, LAYER_C, LAYER_MASK, MAX_RES,
                   check_res, uv_grid, match_channels, conform)
from . import (generate, filters, transform, levels, morph, sdf, composite,
               bridge, control, heightmap, erosion, analysis, terrain,
               flow, splat, regions, lift, hydro,
               pixel, fx, pattern, noisex, stamp, solve, sim, uvx,
               geoimg, hfvis, accel, colorkey, sdf2d, uvshape, coordspace, warp3d,
               filtersim, geolayer)

__all__ = ["CopImage", "DEFAULT_LAYER", "LAYER_C", "LAYER_MASK", "MAX_RES",
           "check_res", "uv_grid", "match_channels", "conform",
           "generate", "filters", "transform", "levels", "morph", "sdf",
           "composite", "bridge", "control", "heightmap", "erosion", "analysis", "terrain",
           "flow", "splat", "regions", "lift", "hydro",
           "pixel", "fx", "pattern", "noisex", "stamp", "solve", "sim", "uvx", "geoimg", "hfvis", "accel",
           "colorkey", "sdf2d", "uvshape", "coordspace", "warp3d", "filtersim", "geolayer"]
