import { useCallback, useState } from 'react'

export interface IdempotencyKeyHandle {
  key: string
  /** Call only when the user starts a genuinely new logical submission (e.g. reopening a create form after success). */
  regenerate: () => void
}

// Stable for the lifetime of one logical form submission, so a network-level
// retry (timeout, double-click) reuses the same Idempotency-Key and the
// backend returns the original cached response instead of creating a
// duplicate (05_api_client_contract.md).
export function useIdempotencyKey(): IdempotencyKeyHandle {
  const [key, setKey] = useState<string>(() => crypto.randomUUID())
  const regenerate = useCallback(() => setKey(crypto.randomUUID()), [])
  return { key, regenerate }
}
