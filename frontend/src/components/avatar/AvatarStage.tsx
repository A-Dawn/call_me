import { useEffect, useMemo, useRef } from 'react'
import { AvatarMotionController } from '@/avatar/motion-controller'
import { DomLayerRenderer } from '@/avatar/renderer'
import type {
  AvatarCharacterConfigV1,
  AvatarCharacterDetail,
  AvatarResolvedData,
  Emotion,
  ResolvedMap,
} from '@/types/avatar'
import { EMOTIONS } from '@/types/avatar'

type AvatarStageProps = {
  activeEmotion: Emotion
  callState: string | null
  speechEnergy: number
  character: AvatarCharacterDetail | null
  fallbackAvatarMap: Record<Emotion, string>
  className?: string
}

type RuntimeSnapshot = {
  config: AvatarCharacterConfigV1
  resolved?: AvatarResolvedData
}

function makeDefaultConfig(): AvatarCharacterConfigV1 {
  return {
    version: '1.0',
    canvas: { width: 1080, height: 1440 },
    fullMap: {
      neutral: null,
      happy: null,
      sad: null,
      angry: null,
      shy: null,
      surprised: null,
    },
    parts: [],
    hitAreas: [],
    reactions: [],
    motions: {
      idle_blink: { enabled: true, min_gap_ms: 2200, max_gap_ms: 5200, close_ms: 110 },
      idle_breath: { enabled: true, amp_px: 4, period_ms: 2400 },
      idle_sway: { enabled: true, deg: 1.0, period_ms: 4200 },
      speaking_lipsync: { enabled: true, sensitivity: 1.0, smooth_ms: 90 },
    },
  }
}

function withReducedMotion(config: AvatarCharacterConfigV1): AvatarCharacterConfigV1 {
  return {
    ...config,
    motions: {
      ...config.motions,
      idle_blink: { ...config.motions.idle_blink, enabled: false },
      idle_breath: { ...config.motions.idle_breath, enabled: false },
      idle_sway: { ...config.motions.idle_sway, enabled: false },
      speaking_lipsync: { ...config.motions.speaking_lipsync, smooth_ms: 0 },
    },
  }
}

function fallbackResolvedMap(fallbackAvatarMap: Record<Emotion, string>): ResolvedMap {
  const out = {} as ResolvedMap
  for (const emo of EMOTIONS) {
    const url = fallbackAvatarMap[emo]
    out[emo] = url
      ? {
          asset_id: `fallback-${emo}`,
          url,
          path: null,
          exists: true,
        }
      : null
  }
  return out
}

function buildRuntimeSnapshot(character: AvatarCharacterDetail | null, fallbackAvatarMap: Record<Emotion, string>): RuntimeSnapshot {
  if (character) return { config: character.config, resolved: character.resolved }
  return {
    config: makeDefaultConfig(),
    resolved: {
      fullMap: fallbackResolvedMap(fallbackAvatarMap),
      parts: [],
    },
  }
}

export function AvatarStage({
  activeEmotion,
  callState,
  speechEnergy,
  character,
  fallbackAvatarMap,
  className,
}: AvatarStageProps) {
  const stageRef = useRef<HTMLDivElement | null>(null)
  const rendererRef = useRef<DomLayerRenderer | null>(null)
  const motionRef = useRef(new AvatarMotionController())
  const reducedMotionRef = useRef(false)
  const snapshotRef = useRef<RuntimeSnapshot>(buildRuntimeSnapshot(character, fallbackAvatarMap))
  const activeEmotionRef = useRef<Emotion>(activeEmotion)
  const callStateRef = useRef<string | null>(callState)
  const speechEnergyRef = useRef(speechEnergy)

  useEffect(() => {
    activeEmotionRef.current = activeEmotion
  }, [activeEmotion])

  useEffect(() => {
    callStateRef.current = callState
  }, [callState])

  useEffect(() => {
    speechEnergyRef.current = speechEnergy
  }, [speechEnergy])

  useEffect(() => {
    snapshotRef.current = buildRuntimeSnapshot(character, fallbackAvatarMap)
  }, [character, fallbackAvatarMap])

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => {
      reducedMotionRef.current = query.matches
    }
    sync()
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const renderer = new DomLayerRenderer()
    renderer.mount(stage)
    rendererRef.current = renderer
    motionRef.current.reset()
    return () => {
      renderer.dispose()
      rendererRef.current = null
    }
  }, [])

  useEffect(() => {
    let rafId = 0
    const tick = (nowMs: number) => {
      const renderer = rendererRef.current
      if (renderer) {
        const source = snapshotRef.current
        const config = reducedMotionRef.current ? withReducedMotion(source.config) : source.config
        const frame = motionRef.current.update({
          nowMs,
          config,
          speaking: callStateRef.current === 'speaking',
          speechEnergy: speechEnergyRef.current,
        })
        renderer.renderFrame({
          config,
          resolved: source.resolved,
          activeEmotion: activeEmotionRef.current,
          blinkClosed: frame.blinkClosed,
          mouthLevel: frame.mouthLevel,
          globalTransform: frame.globalTransform,
        })
      }
      rafId = window.requestAnimationFrame(tick)
    }
    rafId = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(rafId)
  }, [])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return

    const onPointerDown = (event: PointerEvent) => {
      const source = snapshotRef.current
      const config = source.config
      if (!config.hitAreas.length) return

      const rect = stage.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return
      const nx = (event.clientX - rect.left) / rect.width
      const ny = (event.clientY - rect.top) / rect.height

      const hit = config.hitAreas.find(
        (area) =>
          area.enabled &&
          area.shape === 'rect' &&
          nx >= area.x &&
          ny >= area.y &&
          nx <= area.x + area.w &&
          ny <= area.y + area.h,
      )
      if (!hit?.reaction_id) return
      const accepted = motionRef.current.triggerReaction(config, hit.reaction_id, performance.now())
      if (accepted) {
        rendererRef.current?.triggerReaction(hit.reaction_id)
      }
    }

    stage.addEventListener('pointerdown', onPointerDown)
    return () => stage.removeEventListener('pointerdown', onPointerDown)
  }, [])

  const cls = useMemo(() => ['relative h-full w-full overflow-hidden', className].filter(Boolean).join(' '), [className])
  return <div ref={stageRef} className={cls} />
}
