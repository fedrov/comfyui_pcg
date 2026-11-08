// comfyui_pcg/web/pcg_wrangle.js
//
// Since pcg104 this is empty: ch("name") in a Wrangle auto-creating parameters was merged into "custom parameters on any node"
// (web/pcg_spare.js) -- the parameters are now real spare parameters: they can have a type / range / label, take expressions and
// keyframes, be referenced by other nodes, and their values still reach the backend via ch_params.
// The file is kept (empty) so that a stale old version left in an old install does not run alongside the new logic.
export {};
