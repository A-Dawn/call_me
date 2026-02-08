import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'

type AssetsResp = unknown
const EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'shy', 'surprised'] as const
type Emotion = (typeof EMOTIONS)[number]

export function AssetsPage() {
  const [data, setData] = useState<string>('')
  const [file, setFile] = useState<File | null>(null)
  const [emotion, setEmotion] = useState<Emotion>('neutral')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function load() {
    setErr(null)
    try {
      const res = await fetch('/api/assets/?kind=avatar&page=1&page_size=200')
      const json = (await res.json()) as AssetsResp
      setData(JSON.stringify(json, null, 2))
    } catch (e) {
      setErr(String(e))
    }
  }

  async function upload() {
    if (!file) return
    setBusy(true)
    setErr(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('kind', 'avatar')
      fd.append('tags', JSON.stringify([`emotion:${emotion}`]))
      const res = await fetch('/api/assets/upload', {
        method: 'POST',
        body: fd,
      })
      const json = (await res.json()) as unknown
      setData(JSON.stringify(json, null, 2))
      setFile(null)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button onClick={load} variant="secondary">
          GET /api/assets
        </Button>
      </div>
      <Separator />
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={emotion}
          onChange={(e) => setEmotion(e.target.value as Emotion)}
          className="h-10 rounded-md border bg-background px-3 text-sm"
        >
          {EMOTIONS.map((e) => (
            <option key={e} value={e}>
              {e}
            </option>
          ))}
        </select>
        <Input
          type="file"
          accept="image/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button onClick={upload} disabled={!file || busy}>
          POST /api/assets
        </Button>
      </div>
      {err ? <div className="text-sm text-destructive">{err}</div> : null}
      <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3 text-xs">{data}</pre>
    </div>
  )
}
