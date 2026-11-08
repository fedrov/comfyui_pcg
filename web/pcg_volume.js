// comfyui_pcg/web/pcg_volume.js
//
// Volume display in the 3D viewport (pcg106). The backend (geo/volvis.py) decides per volume prim how it is drawn
// and sends a list in header.volumes:
//
//   { mode: "smoke" | "rainbow" | "iso" | "invisible", box: [lo, hi], res: [rx, ry, rz],
//     density_buf, color_buf?, scale, shadow, color, shadowcolor, emit_scale?, emit_max?, emit_color? }
//
// Iso-surfaces arrive as ordinary triangles (the backend extracts them, closed at the grid boundary), so only smoke
// is drawn here: a box per volume whose fragment shader marches the ray through a 3D texture.
//
//   · the density field is optical thickness per unit length, like Houdini's viewport and Mantra:
//     alpha over a step dt = 1 - exp(-density · Density Scale · dt), so the look does not depend on resolution
//   · lighting follows the viewport's headlight (light comes from the camera), with self-shadowing: a short
//     march toward the light per sample; Shadow Scale multiplies the density for that march, and the complement of
//     Shadow Color is a per-channel multiplier on it (Houdini's definition)
//   · colour: Exposed Color × (diffuse field / ramp colour from color_buf rgb); emission (color_buf alpha) is added
//     on top without occluding anything
//   · C is accumulated premultiplied and divided by the final alpha on output, so the ordinary
//     SRC_ALPHA, ONE_MINUS_SRC_ALPHA blending composites it correctly
//
// Depth: when the camera is outside the box the front faces are drawn with the depth test on (geometry in front of
// the volume hides it); inside the box the back faces are drawn without the depth test, so the volume never
// disappears when you fly into it. Geometry inside a volume is therefore covered by the smoke in front of it
// but not composited exactly -- reading the depth buffer would need a separate pass.

const VERT = /* glsl */ `
out vec3 vWorld;
void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vWorld = w.xyz;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const FRAG = /* glsl */ `
precision highp float;
precision highp sampler3D;
uniform sampler3D uDens;
uniform sampler3D uCol;
uniform bool uHasCol;
uniform vec3 uLo;
uniform vec3 uHi;
uniform vec3 uRes;
uniform float uScale;
uniform float uShadow;
uniform float uStep;
uniform vec3 uColor;
uniform vec3 uShadowColor;
uniform vec3 uLight;
uniform float uEmitScale;
uniform float uEmitMax;
uniform vec3 uEmitColor;
in vec3 vWorld;
out vec4 outColor;

vec3 tc(vec3 p) {
  vec3 u = (p - uLo) / max(uHi - uLo, vec3(1e-9));
  return (u * (uRes - 1.0) + 0.5) / uRes;
}
float dens(vec3 p) { return max(texture(uDens, tc(p)).r, 0.0); }

void main() {
  vec3 ro = cameraPosition;
  vec3 rd = normalize(vWorld - ro);
  vec3 inv = 1.0 / rd;
  vec3 t0 = (uLo - ro) * inv, t1 = (uHi - ro) * inv;
  vec3 tmin = min(t0, t1), tmax = max(t0, t1);
  float tn = max(max(tmin.x, tmin.y), max(tmin.z, 0.0));
  float tf = min(min(tmax.x, tmax.y), tmax.z);
  if (tf <= tn) discard;
  float dt = uStep;
  float jit = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
  float t = tn + dt * jit;
  float T = 1.0;
  vec3 C = vec3(0.0);
  float sdt = max(uStep * 2.0, length(uHi - uLo) / 24.0);
  vec3 shadowMul = vec3(1.0) - uShadowColor;
  for (int i = 0; i < 2048; i++) {
    if (t > tf || T < 0.004) break;
    vec3 p = ro + rd * t;
    float d = dens(p) * uScale;
    vec4 c = uHasCol ? texture(uCol, tc(p)) : vec4(1.0, 1.0, 1.0, 0.0);
    if (d > 1e-6) {
      float a = 1.0 - exp(-d * dt);
      float od = 0.0;
      vec3 q = p;
      for (int s = 0; s < 12; s++) {
        q += uLight * sdt;
        if (any(lessThan(q, uLo)) || any(greaterThan(q, uHi))) break;
        od += dens(q) * sdt;
      }
      vec3 Tl = exp(-od * uScale * uShadow * shadowMul);
      vec3 lit = uColor * c.rgb * (0.35 + 0.65 * Tl);
      C += T * a * lit;
      T *= 1.0 - a;
    }
    if (uHasCol && uEmitScale > 0.0) C += T * dt * c.a * uEmitMax * uEmitScale * uEmitColor;
    t += dt;
  }
  float A = 1.0 - T;
  outColor = A > 1e-5 ? vec4(C / A, A) : vec4(0.0);
}`;

function boxLines(T, lo, hi, color) {
  const [a, b, c] = lo, [d, e, f] = hi;
  const P = [
    [a, b, c], [d, b, c], [d, e, c], [a, e, c],
    [a, b, f], [d, b, f], [d, e, f], [a, e, f],
  ];
  const E = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4],
             [0, 4], [1, 5], [2, 6], [3, 7]];
  const pos = new Float32Array(E.length * 6);
  E.forEach(([i, j], k) => { pos.set(P[i], k * 6); pos.set(P[j], k * 6 + 3); });
  const g = new T.BufferGeometry();
  g.setAttribute("position", new T.BufferAttribute(pos, 3));
  return new T.LineSegments(g, new T.LineBasicMaterial({ color, fog: false,
    transparent: true, opacity: 0.55 }));
}

function tex3d(T, data, rx, ry, rz, format, type) {
  const t = new T.Data3DTexture(data, rx, ry, rz);
  t.format = format;
  t.type = type;
  t.minFilter = T.LinearFilter;
  t.magFilter = T.LinearFilter;
  t.wrapS = t.wrapT = t.wrapR = T.ClampToEdgeWrapping;
  t.unpackAlignment = 1;
  t.needsUpdate = true;
  return t;
}

// Smoke box for one volume. Returns a Mesh, or null if the data are missing.
export function smokeMesh(T, v, arrays) {
  const d = arrays[v.density_buf];
  if (!d || !v.res) return null;
  const [rx, ry, rz] = v.res;
  if (d.length !== rx * ry * rz) return null;
  const dens = tex3d(T, d, rx, ry, rz, T.RedFormat, T.HalfFloatType);
  let col = null;
  if (v.color_buf && arrays[v.color_buf] && arrays[v.color_buf].length === rx * ry * rz * 4) {
    col = tex3d(T, arrays[v.color_buf], rx, ry, rz, T.RGBAFormat, T.UnsignedByteType);
  }
  const [lo, hi] = v.box;
  const size = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]].map((s) => Math.max(s, 1e-6));
  const cell = Math.min(size[0] / Math.max(rx - 1, 1), size[1] / Math.max(ry - 1, 1),
                        size[2] / Math.max(rz - 1, 1));
  const diag = Math.hypot(...size);
  // step: 0.8 voxel, but at most ~1500 steps along the diagonal
  const step = Math.max(cell * 0.8, diag / 1500);
  const mat = new T.ShaderMaterial({
    glslVersion: T.GLSL3,
    vertexShader: VERT,
    fragmentShader: FRAG,
    uniforms: {
      uDens: { value: dens },
      uCol: { value: col || dens },
      uHasCol: { value: !!col },
      uLo: { value: new T.Vector3(...lo) },
      uHi: { value: new T.Vector3(...hi) },
      uRes: { value: new T.Vector3(rx, ry, rz) },
      uScale: { value: v.scale ?? 1 },
      uShadow: { value: v.shadow ?? 1 },
      uStep: { value: step },
      uColor: { value: new T.Vector3(...(v.color || [1, 1, 1])) },
      uShadowColor: { value: new T.Vector3(...(v.shadowcolor || [0, 0, 0])) },
      uLight: { value: new T.Vector3(0, 1, 0) },
      uEmitScale: { value: v.emit_scale || 0 },
      uEmitMax: { value: v.emit_max || 0 },
      uEmitColor: { value: new T.Vector3(...(v.emit_color || [1, 1, 1])) },
    },
    transparent: true,
    depthWrite: false,
    side: T.FrontSide,
    fog: false,
  });
  mat.addEventListener("dispose", () => { dens.dispose(); col?.dispose(); });
  const geo = new T.BoxGeometry(size[0], size[1], size[2]);
  const mesh = new T.Mesh(geo, mat);
  mesh.position.set((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
  mesh.renderOrder = 10;                    // after opaque geometry
  mesh.frustumCulled = false;
  const fwd = new T.Vector3();
  mesh.onBeforeRender = (_r, _s, camera) => {
    camera.getWorldDirection(fwd);
    mat.uniforms.uLight.value.copy(fwd).negate();
    const p = camera.position;
    const inside = p.x > lo[0] && p.x < hi[0] && p.y > lo[1] && p.y < hi[1]
                   && p.z > lo[2] && p.z < hi[2];
    const side = inside ? T.BackSide : T.FrontSide;
    if (mat.side !== side) { mat.side = side; mat.depthTest = !inside; mat.needsUpdate = true; }
  };
  mesh.userData.pcgVolume = v;
  return mesh;
}

// All volume objects for the current payload. opts.shading === "wire" draws only bounding boxes.
export function buildVolumes(T, header, arrays, opts) {
  const out = [];
  for (const v of header.volumes || []) {
    const wire = opts && opts.shading === "wire";
    if ((v.mode === "smoke" || v.mode === "rainbow") && !wire) {
      const m = smokeMesh(T, v, arrays);
      if (m) out.push(m);
      else out.push(boxLines(T, v.box[0], v.box[1], 0x9aa7b5));
    } else if (v.mode === "invisible" || wire) {
      out.push(boxLines(T, v.box[0], v.box[1], 0x9aa7b5));
    }
  }
  return out;
}
