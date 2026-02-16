import { Link, type LinkProps, useRouterState } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

type SettingsShellProps = {
  title: string
  description: string
  children: ReactNode
}

const MENU: Array<{ to: LinkProps['to']; label: string }> = [
  { to: '/settings/connection', label: '设备与连接' },
  { to: '/settings/voice-setup', label: '语音配置向导' },
  { to: '/settings/avatar', label: '立绘管理' },
  { to: '/settings/avatar-studio', label: '立绘工作台' },
  { to: '/settings/diagnostics', label: '调试诊断' },
]

export function SettingsShell({ title, description, children }: SettingsShellProps) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-border/70 bg-card/85 p-4 sm:p-5">
        <h1 className="text-lg font-semibold sm:text-xl">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {MENU.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                'rounded-full border px-3 py-1.5 text-sm transition-colors',
                pathname === item.to
                  ? 'border-primary/70 bg-primary/15 text-foreground'
                  : 'border-border/70 bg-background/75 text-muted-foreground hover:text-foreground',
              )}
            >
              {item.label}
            </Link>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-border/70 bg-card/85 p-4 sm:p-5">{children}</section>

      <section className="rounded-2xl border border-border/70 bg-card/70 p-4 sm:p-5">
        <h2 className="text-sm font-medium">兼容入口</h2>
        <p className="mt-1 text-xs text-muted-foreground">旧版工具页面仍可使用，用于历史流程兼容。</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            to="/assets"
            className="rounded-full border border-border/70 bg-background/75 px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            /assets
          </Link>
          <Link
            to="/presets"
            className="rounded-full border border-border/70 bg-background/75 px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            /presets
          </Link>
        </div>
      </section>
    </div>
  )
}
