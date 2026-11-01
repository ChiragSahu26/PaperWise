import * as THREE from 'three'
import type { ToolMeta } from '../tools'

// Portrait sheet in pixels. Landscape art is drawn on a LW x LH canvas and then turned
// a quarter turn into the portrait texture, so the text reads sideways while the stack is
// upright and turns upright as the sheets rotate to horizontal.
export const PW = 1024
export const PH = 1448
export const LW = PH
export const LH = PW
export const BAND = 256 // px of landscape sheet that stays visible in the stack

const INK = '#241c14'
const INK2 = '#6b5b45'
const RULE = '#d9d0bb'

export function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function noise1(seed: number) {
  const r = rng(seed)
  const v = Array.from({ length: 256 }, () => r() * 2 - 1)
  return (x: number) => {
    const i = Math.floor(x)
    const f = x - i
    const a = v[((i % 256) + 256) % 256]
    const b = v[(((i + 1) % 256) + 256) % 256]
    const u = f * f * (3 - 2 * f)
    return a + (b - a) * u
  }
}

const canvas = (w: number, h: number) => {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  return c
}

function tex(c: HTMLCanvasElement, srgb = true) {
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace
  t.anisotropy = 8
  t.needsUpdate = true
  return t
}

export async function loadFonts() {
  const fonts = ['700 120px "Barlow Condensed"', '600 40px "Barlow Condensed"', '400 40px "Source Serif 4"', 'italic 400 40px "Source Serif 4"']
  try {
    await Promise.all(fonts.map((f) => document.fonts.load(f)))
  } catch {
    /* fall back to system fonts */
  }
}

/* --------------------------- glossy backdrop ---------------------------- */

/** A smooth tonal gradient (no grain, no planks). Gloss comes from the material and lights. */
export function backdropTexture(dark: boolean) {
  const S = 1024
  const c = canvas(S, S)
  const g = c.getContext('2d')!
  const base = dark ? '#1a110c' : '#ead69b'
  g.fillStyle = base
  g.fillRect(0, 0, S, S)
  const glow = g.createRadialGradient(S * 0.5, S * 0.46, S * 0.04, S * 0.5, S * 0.5, S * 0.62)
  glow.addColorStop(0, dark ? 'rgba(92,60,38,0.55)' : 'rgba(255,246,206,0.75)')
  glow.addColorStop(0.55, dark ? 'rgba(52,32,20,0.25)' : 'rgba(246,228,168,0.25)')
  glow.addColorStop(1, dark ? 'rgba(0,0,0,0.55)' : 'rgba(196,158,80,0.30)')
  g.fillStyle = glow
  g.fillRect(0, 0, S, S)
  const t = tex(c)
  return t
}

/* ------------------------------ paper pieces ----------------------------- */

export function paperGrainTexture() {
  const c = canvas(512, 512)
  const g = c.getContext('2d')!
  g.fillStyle = '#808080'
  g.fillRect(0, 0, 512, 512)
  const r = rng(5)
  for (let i = 0; i < 9000; i++) {
    const x = r() * 512
    const y = r() * 512
    const a = r() * Math.PI
    const l = 3 + r() * 9
    const v = 100 + Math.floor(r() * 56)
    g.strokeStyle = `rgba(${v},${v},${v},0.5)`
    g.lineWidth = 0.8
    g.beginPath()
    g.moveTo(x, y)
    g.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l)
    g.stroke()
  }
  const t = tex(c, false)
  t.wrapS = t.wrapT = THREE.RepeatWrapping
  t.repeat.set(2, 2.8)
  return t
}

/** White where there is paper, black where there is not. Rough edges for torn sheets. */
export function edgeMask(seed: number, amp: number, inset: number) {
  const c = canvas(PW, PH)
  const g = c.getContext('2d')!
  g.fillStyle = '#000'
  g.fillRect(0, 0, PW, PH)
  const n1 = noise1(seed)
  const n2 = noise1(seed + 1)
  const n3 = noise1(seed + 2)
  const off = (t: number) => n1(t * 0.011) * amp + n2(t * 0.05) * amp * 0.5 + n3(t * 0.23) * amp * 0.2
  const m = inset
  g.beginPath()
  for (let x = m; x <= PW - m; x += 3) g.lineTo(x, m + off(x) + amp)
  for (let y = m; y <= PH - m; y += 3) g.lineTo(PW - m - off(y + 400) - amp, y)
  for (let x = PW - m; x >= m; x -= 3) g.lineTo(x, PH - m - off(x + 900) - amp)
  for (let y = PH - m; y >= m; y -= 3) g.lineTo(m + off(y + 1500) + amp, y)
  g.closePath()
  g.fillStyle = '#fff'
  g.fill()
  return tex(c, false)
}

function paperBase(g: CanvasRenderingContext2D, w: number, h: number) {
  g.fillStyle = '#fbfaf6'
  g.fillRect(0, 0, w, h)
  const gr = g.createRadialGradient(w * 0.5, h * 0.45, h * 0.25, w * 0.5, h * 0.5, w * 0.8)
  gr.addColorStop(0, 'rgba(255,255,255,0)')
  gr.addColorStop(1, 'rgba(170,150,110,0.10)')
  g.fillStyle = gr
  g.fillRect(0, 0, w, h)
}

function edgeShade(g: CanvasRenderingContext2D, w: number, h: number) {
  const e = 34
  const sides: [number, number, number, number, number, number, number, number][] = [
    [0, 0, 0, e, 0, 0, w, e],
    [0, h, 0, h - e, 0, h - e, w, e],
    [0, 0, e, 0, 0, 0, e, h],
    [w, 0, w - e, 0, w - e, 0, e, h],
  ]
  for (const [x0, y0, x1, y1, rx, ry, rw, rh] of sides) {
    const gr = g.createLinearGradient(x0, y0, x1, y1)
    gr.addColorStop(0, 'rgba(90,70,40,0.10)')
    gr.addColorStop(1, 'rgba(90,70,40,0)')
    g.fillStyle = gr
    g.fillRect(rx, ry, rw, rh)
  }
}

function wrap(g: CanvasRenderingContext2D, text: string, x: number, y: number, maxW: number, lh: number, maxLines = 9) {
  const words = text.split(' ')
  let line = ''
  let yy = y
  let n = 0
  for (const word of words) {
    const test = line ? line + ' ' + word : word
    if (g.measureText(test).width > maxW && line) {
      g.fillText(line, x, yy)
      line = word
      yy += lh
      if (++n >= maxLines) return yy
    } else line = test
  }
  if (line) g.fillText(line, x, yy)
  return yy + lh
}

function icon(g: CanvasRenderingContext2D, id: string, x: number, y: number, s: number) {
  g.save()
  g.translate(x, y)
  g.scale(s / 100, s / 100)
  g.strokeStyle = INK
  g.fillStyle = 'none'
  g.lineWidth = 6
  g.lineCap = 'round'
  g.lineJoin = 'round'
  g.beginPath()
  switch (id) {
    case 'ask':
      g.moveTo(12, 18)
      g.lineTo(88, 18)
      g.lineTo(88, 66)
      g.lineTo(46, 66)
      g.lineTo(24, 86)
      g.lineTo(24, 66)
      g.lineTo(12, 66)
      g.closePath()
      g.moveTo(30, 36)
      g.lineTo(70, 36)
      g.moveTo(30, 50)
      g.lineTo(58, 50)
      break
    case 'library':
      g.moveTo(24, 10)
      g.lineTo(62, 10)
      g.lineTo(80, 28)
      g.lineTo(80, 90)
      g.lineTo(24, 90)
      g.closePath()
      g.moveTo(62, 10)
      g.lineTo(62, 28)
      g.lineTo(80, 28)
      g.moveTo(52, 46)
      g.lineTo(52, 74)
      g.moveTo(38, 60)
      g.lineTo(66, 60)
      break
    case 'reader':
      g.moveTo(50, 22)
      g.quadraticCurveTo(30, 12, 8, 20)
      g.lineTo(8, 78)
      g.quadraticCurveTo(30, 70, 50, 82)
      g.quadraticCurveTo(70, 70, 92, 78)
      g.lineTo(92, 20)
      g.quadraticCurveTo(70, 12, 50, 22)
      g.moveTo(50, 22)
      g.lineTo(50, 82)
      break
    case 'check':
      g.moveTo(50, 8)
      g.lineTo(86, 22)
      g.lineTo(86, 52)
      g.quadraticCurveTo(86, 78, 50, 92)
      g.quadraticCurveTo(14, 78, 14, 52)
      g.lineTo(14, 22)
      g.closePath()
      g.moveTo(34, 50)
      g.lineTo(46, 62)
      g.lineTo(68, 38)
      break
    case 'related':
      g.arc(38, 50, 26, 0, Math.PI * 2)
      g.moveTo(88, 50)
      g.arc(62, 50, 26, 0, Math.PI * 2)
      break
    case 'notes':
      g.moveTo(14, 14)
      g.lineTo(86, 14)
      g.lineTo(86, 62)
      g.lineTo(62, 86)
      g.lineTo(14, 86)
      g.closePath()
      g.moveTo(62, 86)
      g.lineTo(62, 62)
      g.lineTo(86, 62)
      g.moveTo(28, 34)
      g.lineTo(70, 34)
      g.moveTo(28, 50)
      g.lineTo(56, 50)
      break
    case 'connections':
      g.arc(22, 26, 10, 0, Math.PI * 2)
      g.moveTo(88, 40)
      g.arc(78, 40, 10, 0, Math.PI * 2)
      g.moveTo(58, 88)
      g.arc(48, 78, 10, 0, Math.PI * 2)
      g.moveTo(31, 31)
      g.lineTo(69, 38)
      g.moveTo(26, 36)
      g.lineTo(44, 68)
      g.moveTo(72, 49)
      g.lineTo(54, 69)
      break
    case 'similarity':
      g.rect(10, 14, 48, 64)
      g.moveTo(42, 28)
      g.rect(42, 28, 48, 64)
      break
  }
  g.stroke()
  g.restore()
}

function arrow(g: CanvasRenderingContext2D, x: number, y: number) {
  g.save()
  g.strokeStyle = INK
  g.lineWidth = 5
  g.lineCap = 'round'
  g.lineJoin = 'round'
  g.beginPath()
  g.arc(x, y, 34, 0, Math.PI * 2)
  g.moveTo(x - 14, y)
  g.lineTo(x + 14, y)
  g.moveTo(x + 4, y - 10)
  g.lineTo(x + 14, y)
  g.lineTo(x + 4, y + 10)
  g.stroke()
  g.restore()
}

/** Landscape art for one sheet. The top BAND px stay visible in the stack. */
function landscapeArt(tool: ToolMeta, front: boolean) {
  const c = canvas(LW, LH)
  const g = c.getContext('2d')!
  paperBase(g, LW, LH)
  const L = 72

  icon(g, tool.id, L, 70, 96)
  g.fillStyle = INK
  g.textBaseline = 'alphabetic'
  g.font = '700 104px "Barlow Condensed", "Arial Narrow", sans-serif'
  g.fillText(tool.title, L + 140, 138)
  g.fillStyle = INK2
  g.font = 'italic 400 38px "Source Serif 4", Georgia, serif'
  g.fillText(tool.blurb, L + 142, 196)
  if (tool.ready) arrow(g, LW - 110, 112)
  else {
    g.font = 'italic 400 34px "Source Serif 4", Georgia, serif'
    g.textAlign = 'right'
    g.fillText('wired up next', LW - L, 118)
    g.textAlign = 'left'
  }
  g.strokeStyle = RULE
  g.lineWidth = 3
  g.beginPath()
  g.moveTo(L, BAND - 14)
  g.lineTo(LW - L, BAND - 14)
  g.stroke()

  g.fillStyle = '#3d3326'
  g.font = '400 50px "Source Serif 4", Georgia, serif'
  if (!front) {
    wrap(g, tool.detail, L, BAND + 62, LW - 2 * L, 70, 3)
  } else {
    // A worked example on the front sheet, so the stack shows what the product does.
    g.font = 'italic 400 34px "Source Serif 4", Georgia, serif'
    g.fillStyle = INK2
    g.fillText('An example', L, BAND + 52)
    g.fillStyle = INK
    g.font = '600 62px "Barlow Condensed", "Arial Narrow", sans-serif'
    g.fillText('What dataset was used?', L, BAND + 132)
    g.strokeStyle = RULE
    g.beginPath()
    g.moveTo(L, BAND + 168)
    g.lineTo(LW - L, BAND + 168)
    g.stroke()
    g.font = '400 50px "Source Serif 4", Georgia, serif'
    const line1 = 'The FloraBench dataset of leaf disease images,'
    const line2 = 'with 18,000 annotated photographs'
    const y1 = BAND + 250
    // highlighter behind the key phrase, like marking the page
    g.fillStyle = 'rgba(255,224,102,0.7)'
    g.fillRect(L + g.measureText('The ').width - 4, y1 - 44, g.measureText('FloraBench dataset').width + 8, 58)
    g.fillStyle = '#3d3326'
    g.fillText(line1, L, y1)
    g.fillText(line2, L, y1 + 70)
    const mx = L + g.measureText(line2).width + 36
    g.fillStyle = '#1f3d73'
    g.beginPath()
    g.arc(mx, y1 + 70 - 16, 26, 0, Math.PI * 2)
    g.fill()
    g.fillStyle = '#fff'
    g.font = '700 38px "Barlow Condensed", sans-serif'
    g.textAlign = 'center'
    g.fillText('1', mx, y1 + 70 - 3)
    g.textAlign = 'left'
    g.fillStyle = INK2
    g.font = 'italic 400 32px "Source Serif 4", Georgia, serif'
    g.fillText('Source 1: eval_paper_1, part 3', L, y1 + 150)
  }
  edgeShade(g, LW, LH)
  return c
}

/** Turn landscape art a quarter turn clockwise into the portrait texture. */
function toPortrait(land: HTMLCanvasElement) {
  const c = canvas(PW, PH)
  const g = c.getContext('2d')!
  g.translate(PW, 0)
  g.rotate(Math.PI / 2)
  g.drawImage(land, 0, 0)
  return c
}

export function sheetTexture(tool: ToolMeta, front: boolean) {
  return tex(toPortrait(landscapeArt(tool, front)))
}

/** The title paper: the topic at the top, upright, on portrait paper. */
export function coverTexture() {
  const c = canvas(PW, PH)
  const g = c.getContext('2d')!
  paperBase(g, PW, PH)
  const L = 96
  g.fillStyle = INK
  g.textBaseline = 'alphabetic'
  let size = 240
  g.font = `700 ${size}px "Barlow Condensed", "Arial Narrow", sans-serif`
  while (g.measureText('PaperWise').width > PW - 2 * L && size > 80) {
    size -= 6
    g.font = `700 ${size}px "Barlow Condensed", "Arial Narrow", sans-serif`
  }
  g.fillText('PaperWise', L - 6, 300)
  g.fillStyle = INK2
  g.font = 'italic 400 56px "Source Serif 4", Georgia, serif'
  g.fillText('Research paper intelligence', L, 388)
  g.strokeStyle = INK
  g.lineWidth = 5
  g.beginPath()
  g.moveTo(L, 440)
  g.lineTo(L + 160, 440)
  g.stroke()
  g.fillStyle = '#3d3326'
  g.font = '400 46px "Source Serif 4", Georgia, serif'
  wrap(g, 'Ask questions of your own papers. Every answer points to the page it came from, and says so when the papers do not have it.', L, 520, PW - 2 * L, 66, 8)
  g.fillStyle = INK2
  g.font = '400 34px "Source Serif 4", Georgia, serif'
  g.fillText('Chirag Sahu, Rudrakshya Shahi and Ujjwal Agarwal', L, PH - 120)
  edgeShade(g, PW, PH)
  return tex(c)
}
