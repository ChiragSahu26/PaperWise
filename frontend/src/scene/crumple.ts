import * as THREE from 'three'

// The title sheet is a flat plane in the XY plane (x: -1..1, y: -1.415..1.415) whose vertices are
// moved in the vertex shader between a crumpled ball and the flat page. Normals are rebuilt by
// finite differences so the creases catch light correctly in both the lit and the shadow pass.

export const crumpleUniforms = {
  uCrumple: { value: 1 },
  uSeed: { value: 3.7 },
}

const GLSL = /* glsl */ `
uniform float uCrumple;
uniform float uSeed;

vec3 hash33(vec3 p){
  p = vec3(dot(p, vec3(127.1, 311.7, 74.7)), dot(p, vec3(269.5, 183.3, 246.1)), dot(p, vec3(113.5, 271.9, 124.6)));
  return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}
float gnoise(vec3 p){
  vec3 i = floor(p); vec3 f = fract(p); vec3 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(mix(dot(hash33(i + vec3(0,0,0)), f - vec3(0,0,0)), dot(hash33(i + vec3(1,0,0)), f - vec3(1,0,0)), u.x),
        mix(dot(hash33(i + vec3(0,1,0)), f - vec3(0,1,0)), dot(hash33(i + vec3(1,1,0)), f - vec3(1,1,0)), u.x), u.y),
    mix(mix(dot(hash33(i + vec3(0,0,1)), f - vec3(0,0,1)), dot(hash33(i + vec3(1,0,1)), f - vec3(1,0,1)), u.x),
        mix(dot(hash33(i + vec3(0,1,1)), f - vec3(0,1,1)), dot(hash33(i + vec3(1,1,1)), f - vec3(1,1,1)), u.x), u.y), u.z);
}
float ridge(vec3 p){ return 1.0 - abs(gnoise(p)); }

vec3 paperSurface(vec2 q){
  float c = uCrumple;
  if (c < 0.0005) return vec3(q, 0.0);

  vec2 n = vec2(q.x, q.y / 1.415);
  // Different parts of the sheet let go at different moments.
  float s = 0.35 * (0.5 + 0.5 * gnoise(vec3(n * 1.8, uSeed)));
  float cv = smoothstep(s, s + 0.65, c * 1.35);

  // Ball: wrap the page around a sphere, centre to the front, corners to the back.
  float r = clamp(length(n) / 1.4142, 0.0, 1.0);
  float phi = atan(n.y, n.x);
  float th = r * 3.14159 * 0.98;
  vec3 dir = vec3(sin(th) * cos(phi), sin(th) * sin(phi), cos(th));
  vec3 v = dir * 1.0 + vec3(uSeed);
  float cr = pow(ridge(v * 1.7), 3.0) * 0.55
           + pow(ridge(v * 3.6 + 7.0), 3.0) * 0.28
           + pow(ridge(v * 7.5 + 13.0), 4.0) * 0.12;
  float radius = 0.80 * (1.0 - 0.24 * cr + 0.12 * gnoise(v * 0.9));
  vec3 ball = dir * radius;

  // Half-open page: still wrinkled while it flattens.
  float wr = sin(3.14159 * cv) * 0.16 * (pow(ridge(vec3(q * 1.6, uSeed + 3.0)), 3.0) - 0.25)
           + sin(3.14159 * cv) * 0.04 * (pow(ridge(vec3(q * 4.2, uSeed + 9.0)), 3.0) - 0.25);
  vec3 flatPage = vec3(q, wr);

  return mix(flatPage, ball, cv);
}
vec3 paperNormal(vec2 q){
  if (uCrumple < 0.0005) return vec3(0.0, 0.0, 1.0);
  float e = 0.012;
  vec3 s0 = paperSurface(q);
  vec3 sx = paperSurface(q + vec2(e, 0.0)) - s0;
  vec3 sy = paperSurface(q + vec2(0.0, e)) - s0;
  return normalize(cross(sx, sy));
}
`

type Shader = { vertexShader: string; fragmentShader: string; uniforms: Record<string, { value: unknown }> }

function patchVertex(shader: Shader, withNormal: boolean) {
  shader.uniforms.uCrumple = crumpleUniforms.uCrumple
  shader.uniforms.uSeed = crumpleUniforms.uSeed
  shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\n' + GLSL)
  shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', 'vec3 transformed = paperSurface(position.xy);')
  if (withNormal) {
    shader.vertexShader = shader.vertexShader.replace('#include <beginnormal_vertex>', 'vec3 objectNormal = paperNormal(position.xy);')
  }
}

/** Standard paper material that can crumple, with an optional second texture to cross-fade to. */
export function crumplePaperMaterial(opts: {
  map: THREE.Texture
  map2: THREE.Texture
  alphaMap: THREE.Texture
  bumpMap: THREE.Texture
}) {
  const mix = { value: 0 }
  const mat = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.93,
    metalness: 0,
    map: opts.map,
    alphaMap: opts.alphaMap,
    alphaTest: 0.5,
    bumpMap: opts.bumpMap,
    bumpScale: 0.5,
    side: THREE.DoubleSide,
  })
  mat.onBeforeCompile = (shader) => {
    patchVertex(shader as unknown as Shader, true)
    shader.uniforms.uMap2 = { value: opts.map2 }
    shader.uniforms.uMix = mix
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform sampler2D uMap2;\nuniform float uMix;')
      .replace(
        '#include <map_fragment>',
        `#ifdef USE_MAP
          vec4 sampledDiffuseColor = mix(texture2D(map, vMapUv), texture2D(uMap2, vMapUv), uMix);
          diffuseColor *= sampledDiffuseColor;
        #endif`,
      )
  }
  mat.customProgramCacheKey = () => 'paperwise-crumple'
  return { material: mat, mix }
}

/** Depth material so the crumpled shape also casts the right shadow. */
export function crumpleDepthMaterial(alphaMap: THREE.Texture) {
  const mat = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, alphaMap, alphaTest: 0.5 })
  mat.onBeforeCompile = (shader) => patchVertex(shader as unknown as Shader, false)
  mat.customProgramCacheKey = () => 'paperwise-crumple-depth'
  return mat
}
