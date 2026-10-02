import type { ICognitoStorage } from 'amazon-cognito-identity-js'

// Per 11_security_and_compliance.md: tokens must never touch localStorage/sessionStorage —
// either is readable by any script on the page, turning a single XSS bug into full session
// theft. amazon-cognito-identity-js defaults its CognitoUserPool to localStorage; this
// adapter swaps it for a plain in-memory map that only lives for the page's lifetime.
export class MemoryStorage implements ICognitoStorage {
  private store = new Map<string, string>()

  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value)
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  clear(): void {
    this.store.clear()
  }
}
