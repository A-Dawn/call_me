import { createContext, useContext, useEffect, type PropsWithChildren } from 'react'
import { useAvatarManager } from '@/hooks/useAvatarManager'

type AvatarManagerContextValue = ReturnType<typeof useAvatarManager>

const AvatarManagerContext = createContext<AvatarManagerContextValue | null>(null)

export function AvatarManagerProvider({ children }: PropsWithChildren) {
  const value = useAvatarManager()

  useEffect(() => {
    void value.loadAvatarSystem()
  }, [value.loadAvatarSystem])

  return <AvatarManagerContext.Provider value={value}>{children}</AvatarManagerContext.Provider>
}

export function useAvatarManagerContext() {
  const value = useContext(AvatarManagerContext)
  if (!value) {
    throw new Error('useAvatarManagerContext must be used within AvatarManagerProvider')
  }
  return value
}
