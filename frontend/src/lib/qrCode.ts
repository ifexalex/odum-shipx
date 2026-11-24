/**
 * Minimal, zero-dependency ISO/IEC 18004 QR Code encoder (Versions 1–5,
 * Byte mode, Error Correction Level L — up to 106 UTF-8 bytes).
 *
 * Used to render a scannable release-note pass on the customer's phone screen
 * for warehouse floor scanners.
 */

interface VersionSpec {
  version: number
  size: number
  dataCodewords: number
  ecCodewords: number
  alignCenter: number | null
}

// ISO/IEC 18004 Table 9 — all Versions 1–5 at ECC-L use a single RS block.
const VERSIONS: VersionSpec[] = [
  { version: 1, size: 21, dataCodewords: 19, ecCodewords: 7, alignCenter: null },
  { version: 2, size: 25, dataCodewords: 34, ecCodewords: 10, alignCenter: 18 },
  { version: 3, size: 29, dataCodewords: 55, ecCodewords: 15, alignCenter: 22 },
  { version: 4, size: 33, dataCodewords: 80, ecCodewords: 20, alignCenter: 26 },
  { version: 5, size: 37, dataCodewords: 108, ecCodewords: 26, alignCenter: 30 },
]

// GF(2^8) tables with primitive polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11d)
const GF_EXP = new Uint8Array(512)
const GF_LOG = new Uint8Array(256)
{
  let x = 1
  for (let i = 0; i < 255; i++) {
    GF_EXP[i] = x
    GF_LOG[x] = i
    x <<= 1
    if (x & 0x100) x ^= 0x11d
  }
  for (let i = 255; i < 512; i++) GF_EXP[i] = GF_EXP[i - 255]!
}

function gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0
  return GF_EXP[GF_LOG[a]! + GF_LOG[b]!]!
}

function rsGenerator(degree: number): Uint8Array {
  let poly: Uint8Array = new Uint8Array([1])
  for (let i = 0; i < degree; i++) {
    const next = new Uint8Array(poly.length + 1)
    const root = GF_EXP[i]!
    for (let j = 0; j < poly.length; j++) {
      next[j] = next[j]! ^ poly[j]!
      next[j + 1] = next[j + 1]! ^ gfMul(poly[j]!, root)
    }
    poly = next
  }
  return poly
}

function rsRemainder(data: Uint8Array, ecLen: number): Uint8Array {
  const gen = rsGenerator(ecLen)
  const rem = new Uint8Array(ecLen)
  for (const byte of data) {
    const factor = byte ^ rem[0]!
    rem.copyWithin(0, 1)
    rem[ecLen - 1] = 0
    if (factor !== 0) {
      for (let j = 0; j < ecLen; j++) {
        rem[j] = rem[j]! ^ gfMul(gen[j + 1]!, factor)
      }
    }
  }
  return rem
}

function formatBits(eccBits: number, mask: number): number {
  const data = (eccBits << 3) | mask
  let rem = data << 10
  for (let i = 14; i >= 10; i--) {
    if ((rem >> i) & 1) rem ^= 0x537 << (i - 10)
  }
  return ((data << 10) | rem) ^ 0x5412
}

function maskBit(mask: number, r: number, c: number): boolean {
  switch (mask) {
    case 0: return (r + c) % 2 === 0
    case 1: return r % 2 === 0
    case 2: return c % 3 === 0
    case 3: return (r + c) % 3 === 0
    case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0
    case 5: return ((r * c) % 2) + ((r * c) % 3) === 0
    case 6: return (((r * c) % 2) + ((r * c) % 3)) % 2 === 0
    default: return (((r + c) % 2) + ((r * c) % 3)) % 2 === 0
  }
}

function buildMatrix(spec: VersionSpec, codewords: Uint8Array, mask: number): boolean[][] {
  const n = spec.size
  const modules: boolean[][] = Array.from({ length: n }, () => Array<boolean>(n).fill(false))
  const isFn: boolean[][] = Array.from({ length: n }, () => Array<boolean>(n).fill(false))

  const setFn = (r: number, c: number, dark: boolean): void => {
    if (r < 0 || r >= n || c < 0 || c >= n) return
    modules[r]![c] = dark
    isFn[r]![c] = true
  }

  // Finder patterns + separators
  const drawFinder = (top: number, left: number): void => {
    for (let dr = -1; dr <= 7; dr++) {
      for (let dc = -1; dc <= 7; dc++) {
        const dist = Math.max(Math.abs(dr - 3), Math.abs(dc - 3))
        setFn(top + dr, left + dc, dist !== 2 && dist !== 4)
      }
    }
  }
  drawFinder(0, 0)
  drawFinder(0, n - 7)
  drawFinder(n - 7, 0)

  // Alignment pattern (Versions 2–5 have a single alignment center)
  if (spec.alignCenter !== null) {
    const c0 = spec.alignCenter
    for (let dr = -2; dr <= 2; dr++) {
      for (let dc = -2; dc <= 2; dc++) {
        const dist = Math.max(Math.abs(dr), Math.abs(dc))
        setFn(c0 + dr, c0 + dc, dist !== 1)
      }
    }
  }

  // Timing patterns
  for (let i = 8; i < n - 8; i++) {
    setFn(6, i, i % 2 === 0)
    setFn(i, 6, i % 2 === 0)
  }

  // Dark module
  setFn(n - 8, 8, true)

  // Format information (ECC Level L = 0b01)
  const fmt = formatBits(0b01, mask)
  // (row, col) placement mirrors the spec's (x = col, y = row) layout.
  for (let i = 0; i <= 5; i++) setFn(i, 8, ((fmt >> i) & 1) === 1)
  setFn(7, 8, ((fmt >> 6) & 1) === 1)
  setFn(8, 8, ((fmt >> 7) & 1) === 1)
  setFn(8, 7, ((fmt >> 8) & 1) === 1)
  for (let i = 9; i < 15; i++) setFn(8, 14 - i, ((fmt >> i) & 1) === 1)

  for (let i = 0; i < 8; i++) setFn(8, n - 1 - i, ((fmt >> i) & 1) === 1)
  for (let i = 8; i < 15; i++) setFn(n - 15 + i, 8, ((fmt >> i) & 1) === 1)

  // Place data + EC bits in zigzag two-column strips
  let bitIdx = 0
  const totalBits = codewords.length * 8
  for (let right = n - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5
    const upward = ((right + 1) & 2) === 0
    for (let vert = 0; vert < n; vert++) {
      const r = upward ? n - 1 - vert : vert
      for (let j = 0; j < 2; j++) {
        const c = right - j
        if (isFn[r]![c]) continue
        let dark = false
        if (bitIdx < totalBits) {
          dark = ((codewords[bitIdx >> 3]! >> (7 - (bitIdx & 7))) & 1) === 1
          bitIdx++
        }
        modules[r]![c] = dark !== maskBit(mask, r, c)
      }
    }
  }
  return modules
}

function penalty(modules: boolean[][]): number {
  const n = modules.length
  let score = 0
  // Horizontal & vertical runs of >= 5
  for (let r = 0; r < n; r++) {
    let runH = 1
    let runV = 1
    for (let c = 1; c < n; c++) {
      if (modules[r]![c] === modules[r]![c - 1]) runH++
      else { if (runH >= 5) score += 3 + (runH - 5); runH = 1 }
      if (modules[c]![r] === modules[c - 1]![r]) runV++
      else { if (runV >= 5) score += 3 + (runV - 5); runV = 1 }
    }
    if (runH >= 5) score += 3 + (runH - 5)
    if (runV >= 5) score += 3 + (runV - 5)
  }
  // 2x2 blocks
  for (let r = 0; r < n - 1; r++) {
    for (let c = 0; c < n - 1; c++) {
      const v = modules[r]![c]
      if (v === modules[r]![c + 1] && v === modules[r + 1]![c] && v === modules[r + 1]![c + 1]) {
        score += 3
      }
    }
  }
  return score
}

/** Encodes a short string into a 2D boolean QR matrix (`true` = dark module), or `null` if too long. */
export function encodeQrMatrix(text: string): boolean[][] | null {
  const bytes = new TextEncoder().encode(text)
  const spec = VERSIONS.find((v) => bytes.length + 2 <= v.dataCodewords)
  if (!spec) return null

  const bits: number[] = []
  const pushBits = (val: number, len: number): void => {
    for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1)
  }

  // Byte mode indicator (0100) + 8-bit length + UTF-8 payload
  pushBits(0b0100, 4)
  pushBits(bytes.length, 8)
  for (const b of bytes) pushBits(b, 8)

  const capacityBits = spec.dataCodewords * 8
  const terminator = Math.min(4, capacityBits - bits.length)
  for (let i = 0; i < terminator; i++) bits.push(0)
  while (bits.length % 8 !== 0) bits.push(0)

  const data = new Uint8Array(spec.dataCodewords)
  for (let i = 0; i < bits.length / 8; i++) {
    let byte = 0
    for (let j = 0; j < 8; j++) byte = (byte << 1) | bits[i * 8 + j]!
    data[i] = byte
  }
  const padBytes = [0xec, 0x11]
  for (let i = bits.length / 8, p = 0; i < spec.dataCodewords; i++, p++) {
    data[i] = padBytes[p % 2]!
  }

  const ec = rsRemainder(data, spec.ecCodewords)
  const codewords = new Uint8Array(data.length + ec.length)
  codewords.set(data, 0)
  codewords.set(ec, data.length)

  let best = buildMatrix(spec, codewords, 0)
  let bestScore = penalty(best)
  for (let mask = 1; mask < 8; mask++) {
    const candidate = buildMatrix(spec, codewords, mask)
    const s = penalty(candidate)
    if (s < bestScore) {
      best = candidate
      bestScore = s
    }
  }
  return best
}
