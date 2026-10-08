import { useEffect } from 'react'

export interface SessionActions {
  refreshNow: () => Promise<void>
  logout: () => void
  exitImpersonation: () => void
}

// The Task 05 API client is a plain module, not a component — it can't call
// useSession() itself. SessionProvider/LocalAuthProvider register their
// actions here on every render so apiRequest() always has a live, correct
// closure to call into on a 401, without React context plumbing through fetch().
let actions: SessionActions | null = null

export function registerSessionActions(next: SessionActions): void {
  actions = next
}

export function getSessionActions(): SessionActions {
  if (!actions) {
    throw new Error('Session actions not registered — mount a SessionProvider/LocalAuthProvider before calling the API')
  }
  return actions
}

export function useRegisterSessionActions(next: SessionActions): void {
  useEffect(() => {
    registerSessionActions(next)
  })
}
