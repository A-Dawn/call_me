import { Link, Outlet, useRouterState } from '@tanstack/react-router'
import { PhoneCall, SlidersHorizontal } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useAtomValue } from 'jotai'
import { connectionAtom } from '@/state/call'
import { CallSessionProvider } from '@/context/call-session-context'
import { AvatarManagerProvider } from '@/context/avatar-manager-context'

export function RootLayout() {
  const conn = useAtomValue(connectionAtom)
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  return (
    <CallSessionProvider>
      <AvatarManagerProvider>
        <div className="min-h-dvh bg-[linear-gradient(180deg,#f5fbff,#edf6ff)] text-foreground">
          <header className="border-b border-border/60 bg-background/80 backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
              <div className="flex items-center gap-2">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <PhoneCall className="h-5 w-5" />
                </div>
                <div className="leading-tight">
                  <div className="text-sm font-semibold">Call Me</div>
                  <div className="text-xs text-muted-foreground">Immersive Voice Call</div>
                </div>
              </div>

              <nav className="flex items-center gap-2">
                <Button
                  asChild
                  variant={pathname.startsWith('/settings') ? 'ghost' : 'secondary'}
                  className={cn('text-sm', conn.status === 'connected' && !pathname.startsWith('/settings') && 'text-primary')}
                >
                  <Link to="/">通话</Link>
                </Button>
                <Button asChild variant={pathname.startsWith('/settings') ? 'secondary' : 'ghost'} className="text-sm">
                  <Link to="/settings/connection">
                    <span className="mr-1 inline-flex">
                      <SlidersHorizontal className="h-4 w-4" />
                    </span>
                    设置
                  </Link>
                </Button>
              </nav>
            </div>
          </header>

          <main className="mx-auto max-w-7xl px-3 py-4 sm:px-6 sm:py-6">
            <Outlet />
          </main>
        </div>
      </AvatarManagerProvider>
    </CallSessionProvider>
  )
}
