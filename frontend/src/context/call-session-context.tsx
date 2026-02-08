import { createContext, useContext, type PropsWithChildren } from 'react'
import { useCallSessionController } from '@/hooks/useCallSession'

type CallSessionContextValue = ReturnType<typeof useCallSessionController>

const CallSessionContext = createContext<CallSessionContextValue | null>(null)

export function CallSessionProvider({ children }: PropsWithChildren) {
  const value = useCallSessionController()
  return <CallSessionContext.Provider value={value}>{children}</CallSessionContext.Provider>
}

export function useCallSession() {
  const value = useContext(CallSessionContext)
  if (!value) {
    throw new Error('useCallSession must be used within CallSessionProvider')
  }
  return value
}
