import { useMemo } from 'react'
import { Link } from '@tanstack/react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useCallSession } from '@/context/call-session-context'
import { SettingsShell } from './settings-shell'

export function SettingsConnectionPage() {
  const { conn, health, httpBaseUrl, wsUrl, connect, disconnect, pingHealth } = useCallSession()

  const statusBadge = useMemo(() => {
    if (conn.status === 'connected') return <Badge>connected</Badge>
    if (conn.status === 'connecting') return <Badge variant="secondary">connecting</Badge>
    return <Badge variant="outline">disconnected</Badge>
  }, [conn.status])

  return (
    <SettingsShell title="设置" description="管理连接、设备与非沉浸式功能。">
      <div className="space-y-5">
        <div className="rounded-xl border border-border/70 bg-background/75 p-4">
          <div className="text-sm font-medium">连接状态</div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {statusBadge}
            {conn.sessionId ? <Badge variant="secondary">{conn.sessionId}</Badge> : null}
            {conn.callState ? <Badge variant="outline">{conn.callState}</Badge> : null}
            <Badge variant="outline">{conn.mic === 'on' ? 'mic:on' : 'mic:off'}</Badge>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {conn.status !== 'connected' ? (
              <Button onClick={connect} data-testid="ws-connect">
                接通
              </Button>
            ) : (
              <Button variant="secondary" onClick={disconnect}>
                挂断
              </Button>
            )}
            <Button variant="outline" onClick={pingHealth}>
              /health
            </Button>
          </div>
        </div>

        <div className="rounded-xl border border-primary/40 bg-primary/5 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium">语音配置向导</div>
              <div className="mt-1 text-xs text-muted-foreground">快速完成 ASR/TTS 配置、模型扫描下载与一键应用。</div>
            </div>
            <Button asChild>
              <Link to="/settings/voice-setup">打开向导</Link>
            </Button>
          </div>
        </div>

        <div className="rounded-xl border border-border/70 bg-background/75 p-4 text-sm">
          <div className="font-medium">接口地址</div>
          <div className="mt-3 space-y-2 font-mono text-xs text-muted-foreground">
            <div>HTTP: {httpBaseUrl}</div>
            <div>WS: {wsUrl}</div>
          </div>
        </div>

        {health ? (
          <pre className="max-h-56 overflow-auto rounded-xl border border-border/70 bg-muted/70 p-3 text-xs">{health}</pre>
        ) : null}
      </div>
    </SettingsShell>
  )
}

