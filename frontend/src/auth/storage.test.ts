import { describe, expect, it } from 'vitest'
import { MemoryStorage } from './storage'

describe('MemoryStorage', () => {
  it('stores, reads, and removes values', () => {
    const storage = new MemoryStorage()
    storage.setItem('a', '1')
    expect(storage.getItem('a')).toBe('1')
    storage.removeItem('a')
    expect(storage.getItem('a')).toBeNull()
  })

  it('returns null for missing keys', () => {
    expect(new MemoryStorage().getItem('missing')).toBeNull()
  })

  it('clears all values', () => {
    const storage = new MemoryStorage()
    storage.setItem('a', '1')
    storage.setItem('b', '2')
    storage.clear()
    expect(storage.getItem('a')).toBeNull()
    expect(storage.getItem('b')).toBeNull()
  })

  it('never touches window.localStorage', () => {
    const spy = { calls: 0 }
    const original = window.localStorage.setItem.bind(window.localStorage)
    window.localStorage.setItem = (...args) => {
      spy.calls += 1
      return original(...args)
    }
    const storage = new MemoryStorage()
    storage.setItem('token', 'secret')
    expect(spy.calls).toBe(0)
    window.localStorage.setItem = original
  })
})
