import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SettingsShell } from './settings-shell'
import { EMOTIONS } from '@/hooks/useAvatarManager'
import type { Emotion } from '@/hooks/useCallSession'
import { useAvatarManagerContext } from '@/context/avatar-manager-context'

export function SettingsAvatarPage() {
  const {
    avatarMap,
    avatarEntries,
    avatarBusy,
    avatarErr,
    loadAvatarMap,
    uploadAvatar,
    deleteAvatar,
  } = useAvatarManagerContext()

  const [targetEmotion, setTargetEmotion] = useState<Emotion>('neutral')
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  const hasCurrentBinding = useMemo(() => Boolean(avatarEntries[targetEmotion]), [avatarEntries, targetEmotion])

  const onUpload = async () => {
    if (!avatarFile) return
    const ok = await uploadAvatar(targetEmotion, avatarFile)
    if (ok) {
      setFeedback(`已上传并绑定：${targetEmotion}`)
      setAvatarFile(null)
    }
  }

  const onDelete = async () => {
    const ok = await deleteAvatar(targetEmotion)
    if (ok) setFeedback(`已删除情绪立绘：${targetEmotion}`)
  }

  return (
    <SettingsShell title="立绘管理" description="上传、绑定、删除各情绪立绘，不影响通话主界面的沉浸布局。">
      <div className="space-y-5">
        <div className="rounded-xl border border-border/70 bg-background/75 p-4">
          <div className="text-sm font-medium">上传与绑定</div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <select
              value={targetEmotion}
              onChange={(e) => setTargetEmotion(e.target.value as Emotion)}
              className="h-10 rounded-md border bg-background px-3 text-sm"
            >
              {EMOTIONS.map((emotion) => (
                <option key={emotion} value={emotion}>
                  {emotion}
                </option>
              ))}
            </select>
            <Input type="file" accept="image/*" onChange={(e) => setAvatarFile(e.target.files?.[0] ?? null)} />
            <Button onClick={() => void onUpload()} disabled={!avatarFile || avatarBusy}>
              上传并绑定
            </Button>
            <Button variant="destructive" disabled={!hasCurrentBinding || avatarBusy} onClick={() => void onDelete()}>
              删除该情绪
            </Button>
            <Button variant="outline" onClick={() => void loadAvatarMap()} disabled={avatarBusy}>
              刷新
            </Button>
          </div>
          {feedback ? <div className="mt-2 text-xs text-emerald-600">{feedback}</div> : null}
          {avatarErr ? <div className="mt-2 text-xs text-destructive">{avatarErr}</div> : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {EMOTIONS.map((emotion) => {
            const img = avatarMap[emotion]
            return (
              <div key={emotion} className="rounded-xl border border-border/70 bg-background/75 p-3">
                <div className="text-sm font-medium">{emotion}</div>
                <div className="mt-2 aspect-[3/4] overflow-hidden rounded-md border border-border/70 bg-muted/60">
                  {img ? (
                    <img src={img} alt={`avatar-${emotion}`} className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">未绑定</div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </SettingsShell>
  )
}
