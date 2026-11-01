import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import type { ToolMeta } from '../tools'
import { backdropTexture, coverTexture, edgeMask, loadFonts, paperGrainTexture, sheetTexture } from './textures'
import { crumplePaperMaterial, crumpleDepthMaterial, crumpleUniforms } from './crumple'

// Scroll timeline (progress 0..1)
//   0.02 - 0.30  the crumpled ball unfolds into a flat torn sheet with the title
//   0.30 - 0.42  the sheet rests
//   0.42 - 0.58  it swings in 3D so the layers behind it show
//   0.56 - 0.90  every sheet turns to landscape and settles into a horizontal stack
const T = {
  unfold: [0.02, 0.3],
  swing: [0.42, 0.58],
  swingBack: [0.6, 0.8],
  stackStart: 0.56,
  stackLen: 0.18,
  stackStagger: 0.022,
  tilt: [0.6, 0.92],
  final: [0.9, 0.96],
} as const

const PWD = 2 // sheet width in world units (portrait)
const PHD = 2.83 // sheet height
const FINAL_SCALE = 1.25
const BAND_STEP = 0.625 // world units of each sheet that stay visible in the stack
const FOV = 35

const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
const seg = (p: number, a: number, b: number) => clamp01((p - a) / (b - a))
const ease = (t: number) => t * t * (3 - 2 * t)
const easeIO = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

export interface SceneCallbacks {
  onHover: (index: number | null) => void
  onPick: (index: number) => void
}

interface Sheet {
  mesh: THREE.Mesh
  jitter: number
  hover: number
}

export class PaperScene {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 80)
  private group = new THREE.Group()
  private sheets: Sheet[] = []
  private backdrop!: THREE.Mesh
  private backdropMat!: THREE.MeshPhysicalMaterial
  private key = new THREE.DirectionalLight(0xfff1da, 2.4)
  private fill = new THREE.HemisphereLight(0xfff6e6, 0x8a6a3a, 0.5)
  private glint = new THREE.PointLight(0xffffff, 40, 40, 1.6)
  private crossMix!: { value: number }
  private textures = { light: null as THREE.Texture | null, dark: null as THREE.Texture | null }

  private target = 0
  private p = 0
  private dark = false
  private enabled = true
  private hovered: number | null = null
  private pointer = new THREE.Vector2(0, 0)
  private pointerSeen = false
  private raf = 0
  private last = 0
  private time = 0
  private reduced = false
  private dist = { paper: 6, stack: 12 }
  private disposed = false
  private raycaster = new THREE.Raycaster()

  private constructor(
    private canvas: HTMLCanvasElement,
    private tools: ToolMeta[],
    private cb: SceneCallbacks,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    this.renderer.toneMapping = THREE.NeutralToneMapping
    this.reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  }

  static async create(canvas: HTMLCanvasElement, tools: ToolMeta[], cb: SceneCallbacks, dark: boolean) {
    await loadFonts()
    const s = new PaperScene(canvas, tools, cb)
    s.dark = dark
    s.build()
    s.resize()
    s.bind()
    s.applyTheme()
    s.last = performance.now()
    s.raf = requestAnimationFrame(s.loop)
    return s
  }

  /* ------------------------------- building ------------------------------ */

  private build() {
    const pm = new THREE.PMREMGenerator(this.renderer)
    this.scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture
    pm.dispose()

    this.camera.position.set(0, 0, 8)

    // Glossy, smooth, yellowish backdrop (no grain). Shine comes from clearcoat and the lights.
    this.backdropMat = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      roughness: 0.3,
      metalness: 0,
      clearcoat: 1,
      clearcoatRoughness: 0.14,
      envMapIntensity: 0.9,
    })
    this.backdrop = new THREE.Mesh(new THREE.PlaneGeometry(46, 32), this.backdropMat)
    this.backdrop.position.z = -1.6
    this.backdrop.receiveShadow = true
    this.scene.add(this.backdrop)

    this.key.position.set(-5, 7, 9)
    this.key.castShadow = true
    this.key.shadow.mapSize.set(2048, 2048)
    const sc = this.key.shadow.camera
    sc.left = -9
    sc.right = 9
    sc.top = 9
    sc.bottom = -9
    sc.near = 1
    sc.far = 40
    this.key.shadow.radius = 6
    this.key.shadow.bias = -0.0004
    this.key.shadow.normalBias = 0.02
    this.scene.add(this.key, this.key.target, this.fill, this.glint)
    this.glint.position.set(2, 1, 7)

    this.scene.add(this.group)

    const grain = paperGrainTexture()
    const geomFlat = new THREE.PlaneGeometry(PWD, PHD, 1, 1)
    const geomCover = new THREE.PlaneGeometry(PWD, PHD, 150, 212)
    const rand = (i: number) => Math.sin(i * 12.9898) * 43758.5453 - Math.floor(Math.sin(i * 12.9898) * 43758.5453)

    this.tools.forEach((tool, k) => {
      const front = k === 0
      const alpha = edgeMask(11 + k * 7, front ? 5 : 1.2, front ? 22 : 10)
      let mesh: THREE.Mesh
      if (front) {
        const { material, mix } = crumplePaperMaterial({
          map: coverTexture(),
          map2: sheetTexture(tool, true),
          alphaMap: alpha,
          bumpMap: grain,
        })
        this.crossMix = mix
        mesh = new THREE.Mesh(geomCover, material)
        mesh.customDepthMaterial = crumpleDepthMaterial(alpha)
      } else {
        const material = new THREE.MeshStandardMaterial({
          color: 0xffffff,
          roughness: 0.93,
          metalness: 0,
          map: sheetTexture(tool, false),
          alphaMap: alpha,
          alphaTest: 0.5,
          bumpMap: grain,
          bumpScale: 0.5,
          side: THREE.DoubleSide,
        })
        mesh = new THREE.Mesh(geomFlat, material)
      }
      mesh.castShadow = true
      mesh.receiveShadow = true
      mesh.frustumCulled = false
      this.group.add(mesh)
      this.sheets.push({ mesh, jitter: (rand(k + 3) - 0.5) * 0.05, hover: 0 })
    })
  }

  private bind() {
    window.addEventListener('resize', this.resize)
    window.addEventListener('pointermove', this.onMove, { passive: true })
    window.addEventListener('click', this.onClick)
    window.addEventListener('pointerleave', this.onLeave)
  }

  /* -------------------------------- public ------------------------------- */

  setProgress(p: number) {
    this.target = clamp01(p)
  }
  setEnabled(on: boolean) {
    this.enabled = on
    if (!on) this.setHover(null)
  }
  setTheme(dark: boolean) {
    this.dark = dark
    this.applyTheme()
  }
  /** Jump to a progress with no easing (used for tests and for reduced motion). */
  snapTo(p: number) {
    this.target = this.p = clamp01(p)
  }
  get isFinal() {
    return this.p > T.final[1] - 0.01
  }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.raf)
    window.removeEventListener('resize', this.resize)
    window.removeEventListener('pointermove', this.onMove)
    window.removeEventListener('click', this.onClick)
    window.removeEventListener('pointerleave', this.onLeave)
    document.body.style.cursor = ''
    this.renderer.dispose()
  }

  /* -------------------------------- theme -------------------------------- */

  private applyTheme() {
    const key = this.dark ? 'dark' : 'light'
    if (!this.textures[key]) this.textures[key] = backdropTexture(this.dark)
    this.backdropMat.map = this.textures[key]
    this.backdropMat.needsUpdate = true
    this.renderer.toneMappingExposure = this.dark ? 0.95 : 1.0
    this.scene.environmentIntensity = this.dark ? 0.35 : 0.7
    this.key.intensity = this.dark ? 1.9 : 2.5
    this.key.color.set(this.dark ? 0xffe2bd : 0xfff1da)
    this.fill.intensity = this.dark ? 0.28 : 0.55
    this.glint.intensity = this.dark ? 22 : 34
    this.glint.color.set(this.dark ? 0xffd9a8 : 0xffffff)
    this.backdropMat.envMapIntensity = this.dark ? 0.55 : 0.9
  }

  /* ------------------------------- resizing ------------------------------ */

  private resize = () => {
    const w = this.canvas.clientWidth || window.innerWidth
    const h = this.canvas.clientHeight || window.innerHeight
    this.renderer.setSize(w, h, false)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    const tan = Math.tan((FOV * Math.PI) / 360)
    const fit = (cw: number, ch: number) => Math.max(ch / 2 / tan, cw / 2 / (tan * this.camera.aspect))
    this.dist.paper = fit(2.5, 3.95)
    const stackH = 7 * BAND_STEP + 2 * FINAL_SCALE + 1.1
    this.dist.stack = fit(PHD * FINAL_SCALE + 0.8, stackH)
  }

  /* ------------------------------ interaction ---------------------------- */

  private onMove = (e: PointerEvent) => {
    this.pointer.set((e.clientX / window.innerWidth) * 2 - 1, -(e.clientY / window.innerHeight) * 2 + 1)
    this.pointerSeen = true
    this.updateHover(e.target as HTMLElement | null)
  }
  private onLeave = () => this.setHover(null)
  private onClick = (e: MouseEvent) => {
    const t = e.target as HTMLElement | null
    if (t?.closest('[data-ui]')) return
    this.pointer.set((e.clientX / window.innerWidth) * 2 - 1, -(e.clientY / window.innerHeight) * 2 + 1)
    this.updateHover(t)
    if (this.hovered != null && this.enabled && this.interactive()) this.cb.onPick(this.hovered)
  }

  private interactive() {
    return this.p > T.final[1] - 0.02
  }

  private updateHover(target: HTMLElement | null) {
    if (!this.enabled || !this.interactive() || target?.closest('[data-ui]')) return this.setHover(null)
    this.group.updateMatrixWorld(true)
    this.raycaster.setFromCamera(this.pointer, this.camera)
    const origin = new THREE.Vector3().setFromMatrixPosition(this.group.matrixWorld)
    const normal = new THREE.Vector3(0, 0, 1).applyQuaternion(this.group.quaternion)
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, origin)
    const hit = new THREE.Vector3()
    if (!this.raycaster.ray.intersectPlane(plane, hit)) return this.setHover(null)
    const local = this.group.worldToLocal(hit)
    const n = this.tools.length
    const halfW = (PHD * FINAL_SCALE) / 2
    const halfH = FINAL_SCALE
    let found: number | null = null
    for (let k = 0; k < n; k++) {
      const y = (k - (n - 1) / 2) * BAND_STEP
      if (Math.abs(local.x) <= halfW && Math.abs(local.y - y) <= halfH) {
        found = k
        break
      }
    }
    this.setHover(found)
  }

  private setHover(i: number | null) {
    if (i === this.hovered) return
    this.hovered = i
    document.body.style.cursor = i != null ? 'pointer' : ''
    this.cb.onHover(i)
  }

  /* --------------------------------- frame ------------------------------- */

  private loop = (now: number) => {
    if (this.disposed) return
    const dt = Math.min(0.05, (now - this.last) / 1000)
    if (!this.enabled && now - this.last < 2000) {
      this.raf = requestAnimationFrame(this.loop)
      return
    }
    this.last = now
    this.time += dt
    const k = this.reduced ? 1 : 1 - Math.exp(-dt * 7)
    this.p += (this.target - this.p) * k
    if (Math.abs(this.target - this.p) < 0.0002) this.p = this.target
    this.update(dt)
    this.renderer.render(this.scene, this.camera)
    this.raf = requestAnimationFrame(this.loop)
  }

  private update(dt: number) {
    const p = this.p
    const n = this.sheets.length

    // 1. unfold
    const c = 1 - easeIO(seg(p, T.unfold[0], T.unfold[1]))
    crumpleUniforms.uCrumple.value = c
    const cover = this.sheets[0].mesh

    // 2. swing: the group turns so the layers behind the front sheet show, then comes back square
    const swingIn = ease(seg(p, T.swing[0], T.swing[1]))
    const swingOut = ease(seg(p, T.swingBack[0], T.swingBack[1]))
    const swing = swingIn * (1 - swingOut)
    const expl = swingIn * (1 - 0.78 * ease(seg(p, T.swingBack[0], 0.9)))
    this.group.rotation.y = -0.62 * swing
    this.group.rotation.x = -0.3 * ease(seg(p, T.tilt[0], T.tilt[1])) + 0.1 * swing

    // 3. sheets turn landscape and stack
    for (let i = 0; i < n; i++) {
      const s = this.sheets[i]
      const start = T.stackStart + T.stackStagger * i
      const t = ease(seg(p, start, start + T.stackLen))
      const targetY = (i - (n - 1) / 2) * BAND_STEP
      const wantHover = this.hovered === i && this.interactive() ? 1 : 0
      s.hover += (wantHover - s.hover) * (this.reduced ? 1 : 1 - Math.exp(-dt * 11))
      const lift = i === 0 ? 0 : 0.72 * s.hover

      s.mesh.position.set(0, lerp(0, targetY, t) + lift, -i * (0.03 + 0.3 * expl) + 0.05 * s.hover)
      s.mesh.rotation.z = lerp(s.jitter, Math.PI / 2, t)
      const appear = i === 0 ? 1 : ease(seg(p, T.unfold[1], T.swing[0] + 0.02))
      s.mesh.visible = appear > 0.001
      s.mesh.scale.setScalar(lerp(1, FINAL_SCALE, t) * Math.max(appear, 0.001))
      if (i > 0) s.mesh.rotation.set(0, 0, lerp(s.jitter, Math.PI / 2, t))
    }

    // the title sheet cross-fades to its stack face while it turns
    const t0 = ease(seg(p, T.stackStart, T.stackStart + T.stackLen))
    this.crossMix.value = ease(seg(t0, 0.3, 0.75))

    // the ball: slow turn and a tiny bob while crumpled, level when flat
    const spin = this.reduced ? 0 : this.time * 0.32
    cover.rotation.set(0.5 * c, (1.1 + spin) * c, 0.18 * c + lerp(this.sheets[0].jitter, Math.PI / 2, t0) * (1 - c))
    cover.position.y += 0.035 * Math.sin(this.time * 1.4) * c

    // camera
    const toStack = ease(seg(p, 0.45, 0.92))
    const room = 1 + 0.1 * Math.sin(Math.PI * seg(p, 0.4, 0.72))
    const dist = lerp(this.dist.paper, this.dist.stack, toStack) * room
    const finalAmt = ease(seg(p, T.final[0], T.final[1]))
    const px = this.pointerSeen ? this.pointer.x : 0
    const py = this.pointerSeen ? this.pointer.y : 0
    this.camera.position.set(px * 0.35 * finalAmt, py * 0.25 * finalAmt, dist)
    this.camera.lookAt(0, 0, 0)

    // moving glint on the glossy backdrop
    this.glint.position.set(Math.sin(p * 5.5) * 5 + px * 1.5, Math.cos(p * 3.2) * 2.2 + py, 6.5)
  }
}
