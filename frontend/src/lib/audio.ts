export function downsampleFloat32(input: Float32Array, inRate: number, outRate: number): Float32Array {
  if (outRate === inRate) return input
  if (outRate > inRate) return input

  const ratio = inRate / outRate
  const outLen = Math.floor(input.length / ratio)
  const out = new Float32Array(outLen)

  let offset = 0
  for (let i = 0; i < outLen; i++) {
    const nextOffset = Math.floor((i + 1) * ratio)
    // average to reduce aliasing a bit
    let sum = 0
    let count = 0
    for (let j = offset; j < nextOffset && j < input.length; j++) {
      sum += input[j]
      count++
    }
    out[i] = count ? sum / count : 0
    offset = nextOffset
  }
  return out
}

export function float32ToPcm16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return out
}

export function bytesToBase64(bytes: Uint8Array): string {
  let bin = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const slice = bytes.subarray(i, i + chunkSize)
    bin += String.fromCharCode(...slice)
  }
  return btoa(bin)
}

export function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}
