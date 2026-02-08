import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

type PresetsResp = unknown

export function PresetsPage() {
  const [data, setData] = useState<string>('')
  const [err, setErr] = useState<string | null>(null)

  async function load() {
    setErr(null)
    try {
      const res = await fetch('/api/presets')
      const json = (await res.json()) as PresetsResp
      setData(JSON.stringify(json, null, 2))
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button onClick={load} variant="secondary">
          GET /api/presets
        </Button>
      </div>
      {err ? <div className="text-sm text-destructive">{err}</div> : null}
      <pre className="max-h-[70vh] overflow-auto rounded-md bg-muted p-3 text-xs">{data}</pre>
    </div>
  )
}
