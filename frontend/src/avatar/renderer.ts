import type { Emotion, AvatarCharacterConfigV1, AvatarPart, AvatarResolvedData, PartSlot } from '@/types/avatar'

export type AvatarRendererFrameInput = {
  config: AvatarCharacterConfigV1
  resolved?: AvatarResolvedData
  activeEmotion: Emotion
  blinkClosed: boolean
  mouthLevel: 0 | 1 | 2
  globalTransform: {
    translateX: number
    translateY: number
    rotateDeg: number
    scale: number
  }
}

export interface AvatarRendererAdapter {
  mount(container: HTMLElement): void
  renderFrame(input: AvatarRendererFrameInput): void
  triggerReaction(reactionId: string): void
  dispose(): void
}

type RenderLayer = {
  key: string
  src: string
  z: number
  opacity: number
  offsetX: number
  offsetY: number
  scale: number
  rotateDeg: number
  anchorX: number
  anchorY: number
  fallback: boolean
}

function partEmotionScore(partEmotion: string, activeEmotion: Emotion): number {
  if (partEmotion === activeEmotion) return 3
  if (partEmotion === 'neutral') return 2
  if (partEmotion === 'all') return 1
  return 0
}

function pickPartBySlot(parts: AvatarPart[], slot: PartSlot, activeEmotion: Emotion): AvatarPart | null {
  let picked: AvatarPart | null = null
  let bestScore = -1
  for (const part of parts) {
    if (!part.enabled) continue
    if (part.slot !== slot) continue
    const score = partEmotionScore(part.emotion, activeEmotion)
    if (score <= 0) continue
    if (!picked) {
      picked = part
      bestScore = score
      continue
    }
    if (score > bestScore) {
      picked = part
      bestScore = score
      continue
    }
    if (score === bestScore && part.z < picked.z) {
      picked = part
    }
  }
  return picked
}

function resolvePartUrl(input: AvatarRendererFrameInput, part: AvatarPart): string | null {
  if (input.resolved?.parts) {
    const resolved = input.resolved.parts.find((x) => x.part_id === part.part_id)
    if (resolved?.url) return resolved.url
  }
  if (part.asset_id) return `/api/assets/${part.asset_id}/file`
  return null
}

function resolveFullMapUrl(input: AvatarRendererFrameInput, emotion: Emotion): string | null {
  const resolved = input.resolved?.fullMap?.[emotion]
  if (resolved?.url) return resolved.url
  const assetId = input.config.fullMap[emotion]
  if (assetId) return `/api/assets/${assetId}/file`
  return null
}

function buildRenderLayers(input: AvatarRendererFrameInput): RenderLayer[] {
  const parts = Array.isArray(input.config.parts) ? input.config.parts : []
  const layers: RenderLayer[] = []
  const usedPartIds = new Set<string>()

  const fullFallback =
    resolveFullMapUrl(input, input.activeEmotion) ||
    resolveFullMapUrl(input, 'neutral') ||
    resolveFullMapUrl(input, 'happy') ||
    resolveFullMapUrl(input, 'sad')

  const bodyBase = pickPartBySlot(parts, 'body_base', input.activeEmotion)
  if (bodyBase) {
    const src = resolvePartUrl(input, bodyBase)
    if (src) {
      usedPartIds.add(bodyBase.part_id)
      layers.push({
        key: `part-${bodyBase.part_id}`,
        src,
        z: bodyBase.z,
        opacity: bodyBase.opacity,
        offsetX: bodyBase.offset_x,
        offsetY: bodyBase.offset_y,
        scale: bodyBase.scale,
        rotateDeg: bodyBase.rotate_deg,
        anchorX: bodyBase.anchor_x,
        anchorY: bodyBase.anchor_y,
        fallback: false,
      })
    }
  } else if (fullFallback) {
    layers.push({
      key: `full-${input.activeEmotion}`,
      src: fullFallback,
      z: -1000,
      opacity: 1,
      offsetX: 0,
      offsetY: 0,
      scale: 1,
      rotateDeg: 0,
      anchorX: 0.5,
      anchorY: 0.5,
      fallback: true,
    })
  }

  const browSlot: PartSlot = input.activeEmotion === 'happy' ? 'brow_happy' : input.activeEmotion === 'sad' ? 'brow_sad' : input.activeEmotion === 'angry' ? 'brow_angry' : 'brow_neutral'
  const eyeSlot: PartSlot = input.blinkClosed ? 'eyes_closed' : 'eyes_open'
  const mouthSlot: PartSlot = input.mouthLevel >= 2 ? 'mouth_open' : input.mouthLevel === 1 ? 'mouth_half' : 'mouth_closed'

  const dynamicSlots: PartSlot[] = [browSlot, eyeSlot, mouthSlot, 'fx_blush', 'fx_sweat']
  for (const slot of dynamicSlots) {
    const part = pickPartBySlot(parts, slot, input.activeEmotion)
    if (!part) continue
    const src = resolvePartUrl(input, part)
    if (!src) continue
    usedPartIds.add(part.part_id)
    layers.push({
      key: `part-${part.part_id}`,
      src,
      z: part.z,
      opacity: part.opacity,
      offsetX: part.offset_x,
      offsetY: part.offset_y,
      scale: part.scale,
      rotateDeg: part.rotate_deg,
      anchorX: part.anchor_x,
      anchorY: part.anchor_y,
      fallback: false,
    })
  }

  for (const part of parts) {
    if (!part.enabled) continue
    if (usedPartIds.has(part.part_id)) continue
    const src = resolvePartUrl(input, part)
    if (!src) continue
    layers.push({
      key: `part-${part.part_id}`,
      src,
      z: part.z,
      opacity: part.opacity,
      offsetX: part.offset_x,
      offsetY: part.offset_y,
      scale: part.scale,
      rotateDeg: part.rotate_deg,
      anchorX: part.anchor_x,
      anchorY: part.anchor_y,
      fallback: false,
    })
  }

  layers.sort((a, b) => a.z - b.z)
  return layers
}

export const __test__ = {
  pickPartBySlot,
  buildRenderLayers,
}

export class DomLayerRenderer implements AvatarRendererAdapter {
  private host: HTMLElement | null = null
  private root: HTMLDivElement | null = null
  private placeholder: HTMLDivElement | null = null
  private imageByKey = new Map<string, HTMLImageElement>()

  mount(container: HTMLElement): void {
    this.host = container
    const root = document.createElement('div')
    root.style.position = 'absolute'
    root.style.inset = '0'
    root.style.transformOrigin = '50% 100%'
    root.style.willChange = 'transform'
    root.style.overflow = 'hidden'
    this.root = root

    const placeholder = document.createElement('div')
    placeholder.style.position = 'absolute'
    placeholder.style.inset = '0'
    placeholder.style.display = 'none'
    placeholder.style.alignItems = 'center'
    placeholder.style.justifyContent = 'center'
    placeholder.style.color = 'hsl(var(--muted-foreground))'
    placeholder.style.fontSize = '0.875rem'
    placeholder.textContent = '请先在设置页上传立绘素材'
    this.placeholder = placeholder

    container.appendChild(root)
    container.appendChild(placeholder)
  }

  private ensureImage(key: string): HTMLImageElement {
    const existing = this.imageByKey.get(key)
    if (existing) return existing
    const img = document.createElement('img')
    img.dataset.layer = key
    img.alt = key
    img.style.position = 'absolute'
    img.style.inset = '0'
    img.style.width = '100%'
    img.style.height = '100%'
    img.style.pointerEvents = 'none'
    img.style.userSelect = 'none'
    img.style.objectFit = 'contain'
    img.draggable = false
    this.imageByKey.set(key, img)
    return img
  }

  renderFrame(input: AvatarRendererFrameInput): void {
    const root = this.root
    const placeholder = this.placeholder
    if (!root || !placeholder) return

    const layers = buildRenderLayers(input)
    root.style.transform = `translate(${input.globalTransform.translateX.toFixed(2)}px, ${input.globalTransform.translateY.toFixed(2)}px) rotate(${input.globalTransform.rotateDeg.toFixed(2)}deg) scale(${input.globalTransform.scale.toFixed(4)})`

    if (layers.length === 0) {
      for (const el of this.imageByKey.values()) el.remove()
      this.imageByKey.clear()
      placeholder.style.display = 'flex'
      return
    }
    placeholder.style.display = 'none'

    const keep = new Set<string>()
    for (const layer of layers) {
      keep.add(layer.key)
      const img = this.ensureImage(layer.key)
      if (img.src !== layer.src) img.src = layer.src
      img.style.zIndex = String(layer.z)
      img.style.opacity = layer.opacity.toFixed(4)
      img.style.objectFit = layer.fallback ? 'cover' : 'contain'
      img.style.transformOrigin = `${(layer.anchorX * 100).toFixed(2)}% ${(layer.anchorY * 100).toFixed(2)}%`
      img.style.transform = `translate(${layer.offsetX.toFixed(2)}px, ${layer.offsetY.toFixed(2)}px) rotate(${layer.rotateDeg.toFixed(2)}deg) scale(${layer.scale.toFixed(4)})`
      if (!img.parentElement) root.appendChild(img)
    }

    for (const [key, img] of this.imageByKey.entries()) {
      if (keep.has(key)) continue
      img.remove()
      this.imageByKey.delete(key)
    }
  }

  triggerReaction(reactionId: string): void {
    const host = this.host
    if (!host) return
    host.style.setProperty('--avatar-reaction', reactionId)
  }

  dispose(): void {
    for (const img of this.imageByKey.values()) img.remove()
    this.imageByKey.clear()
    if (this.root) this.root.remove()
    if (this.placeholder) this.placeholder.remove()
    this.root = null
    this.placeholder = null
    this.host = null
  }
}
