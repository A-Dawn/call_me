import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { AvatarStage } from '@/components/avatar/AvatarStage'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EMOTIONS, PART_SLOTS, type AvatarCharacterConfigV1, type AvatarHitArea, type Emotion, type PartEmotion, type PartSlot } from '@/types/avatar'
import { SettingsShell } from './settings-shell'
import { useAvatarManagerContext } from '@/context/avatar-manager-context'

function cloneConfig(config: AvatarCharacterConfigV1): AvatarCharacterConfigV1 {
  return JSON.parse(JSON.stringify(config)) as AvatarCharacterConfigV1
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min
  if (value > max) return max
  return value
}

function makeHitArea(id: string, reactionId: string): AvatarHitArea {
  return {
    id,
    label: id,
    shape: 'rect',
    x: 0.35,
    y: 0.2,
    w: 0.2,
    h: 0.18,
    reaction_id: reactionId,
    enabled: true,
  }
}

type DragState = {
  id: string
  mode: 'move' | 'resize'
  startX: number
  startY: number
  startArea: AvatarHitArea
}

export function SettingsAvatarStudioPage() {
  const {
    avatarMap,
    avatarBusy,
    avatarErr,
    characters,
    activeCharacterId,
    activeCharacter,
    loadAvatarSystem,
    loadCharacter,
    uploadAsset,
    createCharacter,
    setActiveCharacter,
    deleteCharacter,
    saveCharacterConfig,
  } = useAvatarManagerContext()
  const [selectedCharacterId, setSelectedCharacterId] = useState('')
  const [draftConfig, setDraftConfig] = useState<AvatarCharacterConfigV1 | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [newCharacterName, setNewCharacterName] = useState('My Avatar')
  const [fullEmotion, setFullEmotion] = useState<Emotion>('neutral')
  const [fullFile, setFullFile] = useState<File | null>(null)
  const [partSlot, setPartSlot] = useState<PartSlot>('body_base')
  const [partEmotion, setPartEmotion] = useState<PartEmotion>('all')
  const [partFile, setPartFile] = useState<File | null>(null)
  const [previewEmotion, setPreviewEmotion] = useState<Emotion>('neutral')
  const [previewEnergy, setPreviewEnergy] = useState(0.4)
  const [selectedHitId, setSelectedHitId] = useState<string | null>(null)
  const dragRef = useRef<DragState | null>(null)
  const hitEditorRef = useRef<HTMLDivElement | null>(null)

  const previewCharacter = useMemo(() => {
    if (!draftConfig) return null
    return {
      character_id: selectedCharacterId || 'preview',
      owner_id: '',
      name: 'preview',
      renderer_kind: 'dom2d',
      schema_version: '1.0',
      created_at: null,
      updated_at: null,
      config: draftConfig,
      resolved: undefined,
    }
  }, [draftConfig, selectedCharacterId])

  useEffect(() => {
    if (!characters.length) {
      setSelectedCharacterId('')
      return
    }
    if (!selectedCharacterId) {
      setSelectedCharacterId(activeCharacterId || characters[0].character_id)
      return
    }
    if (!characters.some((item) => item.character_id === selectedCharacterId)) {
      setSelectedCharacterId(activeCharacterId || characters[0].character_id)
    }
  }, [activeCharacterId, characters, selectedCharacterId])

  useEffect(() => {
    let disposed = false
    const run = async () => {
      if (!selectedCharacterId) return
      if (activeCharacter?.character_id === selectedCharacterId) {
        setDraftConfig(cloneConfig(activeCharacter.config))
        return
      }
      const detail = await loadCharacter(selectedCharacterId)
      if (!disposed && detail) {
        setDraftConfig(cloneConfig(detail.config))
      }
    }
    void run().catch((e) => {
      if (!disposed) setFeedback(`加载角色失败: ${String(e)}`)
    })
    return () => {
      disposed = true
    }
  }, [activeCharacter, loadCharacter, selectedCharacterId])

  const selectedCharacterName = useMemo(
    () => characters.find((item) => item.character_id === selectedCharacterId)?.name || '',
    [characters, selectedCharacterId],
  )

  const selectedHitArea = useMemo(() => {
    if (!draftConfig || !selectedHitId) return null
    return draftConfig.hitAreas.find((item) => item.id === selectedHitId) || null
  }, [draftConfig, selectedHitId])

  const patchConfig = useCallback((updater: (prev: AvatarCharacterConfigV1) => AvatarCharacterConfigV1) => {
    setDraftConfig((prev) => {
      if (!prev) return prev
      return updater(prev)
    })
  }, [])

  const updateHitArea = useCallback(
    (id: string, patch: Partial<AvatarHitArea>) => {
      patchConfig((prev) => {
        const next = cloneConfig(prev)
        const idx = next.hitAreas.findIndex((x) => x.id === id)
        if (idx < 0) return prev
        next.hitAreas[idx] = { ...next.hitAreas[idx], ...patch }
        return next
      })
    },
    [patchConfig],
  )

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      const dragging = dragRef.current
      const editor = hitEditorRef.current
      if (!dragging || !editor) return
      const rect = editor.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return
      const dx = (event.clientX - dragging.startX) / rect.width
      const dy = (event.clientY - dragging.startY) / rect.height
      updateHitArea(
        dragging.id,
        dragging.mode === 'move'
          ? {
              x: clamp(dragging.startArea.x + dx, 0, 1 - dragging.startArea.w),
              y: clamp(dragging.startArea.y + dy, 0, 1 - dragging.startArea.h),
            }
          : {
              w: clamp(dragging.startArea.w + dx, 0.05, 1 - dragging.startArea.x),
              h: clamp(dragging.startArea.h + dy, 0.05, 1 - dragging.startArea.y),
            },
      )
    }
    const onPointerUp = () => {
      dragRef.current = null
    }
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
    }
  }, [updateHitArea])

  const onCreateCharacter = async () => {
    const ok = await createCharacter(newCharacterName || 'New Character', true)
    if (ok) {
      setFeedback(`已创建角色：${newCharacterName || 'New Character'}`)
    }
  }

  const onSetActive = async () => {
    if (!selectedCharacterId) return
    const ok = await setActiveCharacter(selectedCharacterId)
    if (ok) {
      setFeedback(`已切换激活角色：${selectedCharacterName || selectedCharacterId}`)
    }
  }

  const onDeleteCharacter = async () => {
    if (!selectedCharacterId) return
    const ok = await deleteCharacter(selectedCharacterId)
    if (ok) {
      setFeedback(`已删除角色：${selectedCharacterName || selectedCharacterId}`)
    }
  }

  const onUploadFull = async () => {
    if (!draftConfig || !fullFile) return
    try {
      const uploaded = await uploadAsset(fullFile, { kind: 'avatar', tags: [`emotion:${fullEmotion}`] })
      patchConfig((prev) => {
        const next = cloneConfig(prev)
        next.fullMap[fullEmotion] = uploaded.asset_id
        return next
      })
      setFullFile(null)
      setFeedback(`已上传整图并设置 ${fullEmotion}`)
    } catch (e) {
      setFeedback(`整图上传失败: ${String(e)}`)
    }
  }

  const onUploadPart = async () => {
    if (!draftConfig || !partFile) return
    try {
      const uploaded = await uploadAsset(partFile, {
        kind: 'avatar_part',
        tags: [`slot:${partSlot}`, `emotion:${partEmotion}`],
      })
      patchConfig((prev) => {
        const next = cloneConfig(prev)
        next.parts.push({
          part_id: (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          slot: partSlot,
          emotion: partEmotion,
          asset_id: uploaded.asset_id,
          z: next.parts.length + 1,
          anchor_x: 0.5,
          anchor_y: 1.0,
          offset_x: 0,
          offset_y: 0,
          scale: 1,
          rotate_deg: 0,
          opacity: 1,
          enabled: true,
        })
        return next
      })
      setPartFile(null)
      setFeedback(`已上传部件 ${partSlot}/${partEmotion}`)
    } catch (e) {
      setFeedback(`部件上传失败: ${String(e)}`)
    }
  }

  const onSave = async () => {
    if (!selectedCharacterId || !draftConfig) return
    const ok = await saveCharacterConfig(selectedCharacterId, draftConfig)
    if (ok) setFeedback(`已保存角色配置：${selectedCharacterName || selectedCharacterId}`)
  }

  const onReload = async () => {
    await loadAvatarSystem()
    setFeedback('已刷新角色与映射')
  }

  const onStartDrag = (event: ReactPointerEvent, area: AvatarHitArea, mode: 'move' | 'resize') => {
    event.preventDefault()
    event.stopPropagation()
    dragRef.current = {
      id: area.id,
      mode,
      startX: event.clientX,
      startY: event.clientY,
      startArea: { ...area },
    }
    setSelectedHitId(area.id)
  }

  return (
    <SettingsShell title="立绘工作台" description="角色化立绘编辑：整图+部件混合、触区反馈、微动作参数、实时预览与发布。">
      <div className="space-y-5">
        <div className="rounded-xl border border-border/70 bg-background/75 p-4">
          <div className="text-sm font-medium">角色管理</div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <select
              value={selectedCharacterId}
              onChange={(e) => setSelectedCharacterId(e.target.value)}
              data-testid="studio-character-select"
              className="h-10 min-w-[16rem] rounded-md border bg-background px-3 text-sm"
            >
              {characters.map((item) => (
                <option key={item.character_id} value={item.character_id}>
                  {item.name} {item.character_id === activeCharacterId ? '(active)' : ''}
                </option>
              ))}
            </select>
            <Input
              value={newCharacterName}
              onChange={(e) => setNewCharacterName(e.target.value)}
              placeholder="新角色名"
              className="max-w-44"
              data-testid="studio-new-character-name"
            />
            <Button onClick={() => void onCreateCharacter()} disabled={avatarBusy} data-testid="studio-create-character">
              新建
            </Button>
            <Button
              variant="secondary"
              onClick={() => void onSetActive()}
              disabled={!selectedCharacterId || selectedCharacterId === activeCharacterId || avatarBusy}
              data-testid="studio-set-active"
            >
              设为激活
            </Button>
            <Button
              variant="destructive"
              onClick={() => void onDeleteCharacter()}
              disabled={!selectedCharacterId || selectedCharacterId === activeCharacterId || avatarBusy}
              data-testid="studio-delete-character"
            >
              删除
            </Button>
            <Button variant="outline" onClick={() => void onReload()} disabled={avatarBusy}>
              刷新
            </Button>
          </div>
          {feedback ? <div className="mt-2 text-xs text-emerald-700">{feedback}</div> : null}
          {avatarErr ? <div className="mt-2 text-xs text-destructive">{avatarErr}</div> : null}
        </div>

        <div className="grid gap-5 xl:grid-cols-[380px_1fr]">
          <div className="space-y-4">
            <div className="rounded-xl border border-border/70 bg-background/75 p-4">
              <div className="text-sm font-medium">整图素材（fullMap）</div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <select
                  value={fullEmotion}
                  onChange={(e) => setFullEmotion(e.target.value as Emotion)}
                  data-testid="studio-full-emotion"
                  className="h-10 rounded-md border bg-background px-3 text-sm"
                >
                  {EMOTIONS.map((emotion) => (
                    <option key={emotion} value={emotion}>
                      {emotion}
                    </option>
                  ))}
                </select>
                <Input
                  type="file"
                  accept="image/*"
                  onChange={(e) => setFullFile(e.target.files?.[0] ?? null)}
                  data-testid="studio-full-file"
                />
                <Button onClick={() => void onUploadFull()} disabled={!draftConfig || !fullFile || avatarBusy} data-testid="studio-upload-full">
                  上传整图
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-border/70 bg-background/75 p-4">
              <div className="text-sm font-medium">部件素材（parts）</div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <select
                  value={partSlot}
                  onChange={(e) => setPartSlot(e.target.value as PartSlot)}
                  data-testid="studio-part-slot"
                  className="h-10 rounded-md border bg-background px-3 text-sm"
                >
                  {PART_SLOTS.map((slot) => (
                    <option key={slot} value={slot}>
                      {slot}
                    </option>
                  ))}
                </select>
                <select
                  value={partEmotion}
                  onChange={(e) => setPartEmotion(e.target.value as PartEmotion)}
                  data-testid="studio-part-emotion"
                  className="h-10 rounded-md border bg-background px-3 text-sm"
                >
                  <option value="all">all</option>
                  {EMOTIONS.map((emotion) => (
                    <option key={emotion} value={emotion}>
                      {emotion}
                    </option>
                  ))}
                </select>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Input
                  type="file"
                  accept="image/*"
                  onChange={(e) => setPartFile(e.target.files?.[0] ?? null)}
                  data-testid="studio-part-file"
                />
                <Button onClick={() => void onUploadPart()} disabled={!draftConfig || !partFile || avatarBusy} data-testid="studio-upload-part">
                  上传部件
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-border/70 bg-background/75 p-4">
              <div className="text-sm font-medium">动作参数</div>
              {draftConfig ? (
                <div className="mt-3 space-y-3 text-sm">
                  <label className="block">
                    呼吸振幅 {draftConfig.motions.idle_breath.amp_px.toFixed(1)}px
                    <input
                      className="mt-1 w-full"
                      type="range"
                      min={0}
                      max={20}
                      step={0.1}
                      value={draftConfig.motions.idle_breath.amp_px}
                      onChange={(e) =>
                        patchConfig((prev) => ({
                          ...prev,
                          motions: {
                            ...prev.motions,
                            idle_breath: { ...prev.motions.idle_breath, amp_px: Number(e.target.value) },
                          },
                        }))
                      }
                    />
                  </label>
                  <label className="block">
                    轻摆角度 {draftConfig.motions.idle_sway.deg.toFixed(2)}deg
                    <input
                      className="mt-1 w-full"
                      type="range"
                      min={0}
                      max={8}
                      step={0.05}
                      value={draftConfig.motions.idle_sway.deg}
                      onChange={(e) =>
                        patchConfig((prev) => ({
                          ...prev,
                          motions: {
                            ...prev.motions,
                            idle_sway: { ...prev.motions.idle_sway, deg: Number(e.target.value) },
                          },
                        }))
                      }
                    />
                  </label>
                  <label className="block">
                    口型灵敏度 {draftConfig.motions.speaking_lipsync.sensitivity.toFixed(2)}
                    <input
                      className="mt-1 w-full"
                      type="range"
                      min={0.2}
                      max={3}
                      step={0.05}
                      value={draftConfig.motions.speaking_lipsync.sensitivity}
                      onChange={(e) =>
                        patchConfig((prev) => ({
                          ...prev,
                          motions: {
                            ...prev.motions,
                            speaking_lipsync: { ...prev.motions.speaking_lipsync, sensitivity: Number(e.target.value) },
                          },
                        }))
                      }
                    />
                  </label>
                </div>
              ) : (
                <div className="mt-2 text-xs text-muted-foreground">请选择角色后编辑</div>
              )}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-xl border border-border/70 bg-background/75 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-sm font-medium">实时预览</div>
                <select
                  value={previewEmotion}
                  onChange={(e) => setPreviewEmotion(e.target.value as Emotion)}
                  className="h-8 rounded-md border bg-background px-2 text-xs"
                >
                  {EMOTIONS.map((emotion) => (
                    <option key={emotion} value={emotion}>
                      {emotion}
                    </option>
                  ))}
                </select>
                <label className="text-xs text-muted-foreground">
                  speaking energy
                  <input
                    className="ml-2 align-middle"
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={previewEnergy}
                    onChange={(e) => setPreviewEnergy(Number(e.target.value))}
                  />
                </label>
              </div>

              <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_280px]">
                <div className="relative overflow-hidden rounded-xl border border-border/70 bg-background/60">
                  <AvatarStage
                    activeEmotion={previewEmotion}
                    callState="speaking"
                    speechEnergy={previewEnergy}
                    character={previewCharacter}
                    fallbackAvatarMap={avatarMap}
                    className="min-h-[28rem]"
                  />
                </div>
                <div className="space-y-2 rounded-xl border border-border/70 bg-background/80 p-3">
                  <div className="text-xs font-medium text-muted-foreground">触区编辑（拖拽移动/右下角缩放）</div>
                  <div ref={hitEditorRef} className="relative aspect-[3/4] overflow-hidden rounded-md border border-border/70 bg-muted/50">
                    <AvatarStage
                      activeEmotion={previewEmotion}
                      callState={null}
                      speechEnergy={0}
                      character={previewCharacter}
                      fallbackAvatarMap={avatarMap}
                      className="h-full"
                    />
                    {draftConfig?.hitAreas.map((area) => (
                      <div
                        key={area.id}
                        role="button"
                        tabIndex={0}
                        onPointerDown={(e) => onStartDrag(e, area, 'move')}
                        className={`absolute border ${selectedHitId === area.id ? 'border-emerald-500 bg-emerald-500/10' : 'border-white/80 bg-white/10'}`}
                        style={{
                          left: `${area.x * 100}%`,
                          top: `${area.y * 100}%`,
                          width: `${area.w * 100}%`,
                          height: `${area.h * 100}%`,
                        }}
                      >
                        <div className="pointer-events-none absolute left-1 top-1 rounded bg-black/60 px-1 py-0.5 text-[10px] text-white">{area.id}</div>
                        <div
                          onPointerDown={(e) => onStartDrag(e, area, 'resize')}
                          className="absolute bottom-0 right-0 h-3 w-3 cursor-se-resize rounded-tl bg-white/80"
                        />
                      </div>
                    ))}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        patchConfig((prev) => {
                          const next = cloneConfig(prev)
                          next.hitAreas.push(makeHitArea(`area_${Date.now().toString(36)}`, 'pat_head'))
                          return next
                        })
                      }
                      disabled={!draftConfig}
                      data-testid="studio-add-hit-area"
                    >
                      新增触区
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() =>
                        patchConfig((prev) => ({
                          ...prev,
                          hitAreas: prev.hitAreas.filter((item) => item.id !== selectedHitId),
                        }))
                      }
                      disabled={!draftConfig || !selectedHitId}
                    >
                      删除触区
                    </Button>
                  </div>

                  {selectedHitArea ? (
                    <div className="space-y-2 text-xs">
                      <Input
                        value={selectedHitArea.label}
                        onChange={(e) => updateHitArea(selectedHitArea.id, { label: e.target.value })}
                        placeholder="触区标题"
                      />
                      <Input
                        value={selectedHitArea.reaction_id}
                        onChange={(e) => updateHitArea(selectedHitArea.id, { reaction_id: e.target.value })}
                        placeholder="reaction_id"
                      />
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border/70 bg-background/75 p-4">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium">部件列表（可微调层级与位置）</div>
                <Button onClick={() => void onSave()} disabled={!draftConfig || !selectedCharacterId || avatarBusy} data-testid="studio-save-publish">
                  保存发布
                </Button>
              </div>
              <div className="mt-3 max-h-[20rem] space-y-2 overflow-auto">
                {draftConfig?.parts.length ? (
                  draftConfig.parts.map((part) => (
                    <div key={part.part_id} className="grid gap-2 rounded-lg border border-border/70 bg-background/70 p-2 sm:grid-cols-12">
                      <select
                        value={part.slot}
                        onChange={(e) =>
                          patchConfig((prev) => ({
                            ...prev,
                            parts: prev.parts.map((item) => (item.part_id === part.part_id ? { ...item, slot: e.target.value as PartSlot } : item)),
                          }))
                        }
                        className="sm:col-span-3 h-8 rounded border bg-background px-2 text-xs"
                      >
                        {PART_SLOTS.map((slot) => (
                          <option key={slot} value={slot}>
                            {slot}
                          </option>
                        ))}
                      </select>
                      <select
                        value={part.emotion}
                        onChange={(e) =>
                          patchConfig((prev) => ({
                            ...prev,
                            parts: prev.parts.map((item) =>
                              item.part_id === part.part_id ? { ...item, emotion: e.target.value as PartEmotion } : item,
                            ),
                          }))
                        }
                        className="sm:col-span-2 h-8 rounded border bg-background px-2 text-xs"
                      >
                        <option value="all">all</option>
                        {EMOTIONS.map((emo) => (
                          <option key={emo} value={emo}>
                            {emo}
                          </option>
                        ))}
                      </select>
                      <Input
                        type="number"
                        value={part.z}
                        onChange={(e) =>
                          patchConfig((prev) => ({
                            ...prev,
                            parts: prev.parts.map((item) => (item.part_id === part.part_id ? { ...item, z: Number(e.target.value) } : item)),
                          }))
                        }
                        className="sm:col-span-1 h-8 text-xs"
                      />
                      <Input
                        type="number"
                        value={part.offset_x}
                        onChange={(e) =>
                          patchConfig((prev) => ({
                            ...prev,
                            parts: prev.parts.map((item) => (item.part_id === part.part_id ? { ...item, offset_x: Number(e.target.value) } : item)),
                          }))
                        }
                        className="sm:col-span-2 h-8 text-xs"
                      />
                      <Input
                        type="number"
                        value={part.offset_y}
                        onChange={(e) =>
                          patchConfig((prev) => ({
                            ...prev,
                            parts: prev.parts.map((item) => (item.part_id === part.part_id ? { ...item, offset_y: Number(e.target.value) } : item)),
                          }))
                        }
                        className="sm:col-span-2 h-8 text-xs"
                      />
                      <Button
                        variant="destructive"
                        size="sm"
                        className="sm:col-span-2"
                        onClick={() =>
                          patchConfig((prev) => ({
                            ...prev,
                            parts: prev.parts.filter((item) => item.part_id !== part.part_id),
                          }))
                        }
                      >
                        删除
                      </Button>
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-muted-foreground">暂无部件，上传 `eyes/mouth/body` 等素材后可在这里微调。</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </SettingsShell>
  )
}
