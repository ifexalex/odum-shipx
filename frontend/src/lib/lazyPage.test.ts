import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { lazyNamed } from './lazyPage'

// React.lazy keeps the loader in an internal payload; running it is what the test needs, so read it back.
function runLoader(component: ReturnType<typeof lazyNamed>): Promise<{ default: unknown }> {
  const payload = (component as unknown as { _payload: { _result: () => Promise<{ default: unknown }> } })._payload
  return payload._result()
}

describe('lazyNamed', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const Page = () => null

  it('resolves the named export as the default React.lazy needs', async () => {
    const load = vi.fn().mockResolvedValue({ Page })
    const result = await runLoader(lazyNamed(load, 'Page'))
    expect(result.default).toBe(Page)
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('tries again once when the chunk fails to load (a dropped connection)', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('Failed to fetch dynamically imported module')).mockResolvedValue({ Page })
    const pending = runLoader(lazyNamed(load, 'Page'))
    await vi.runAllTimersAsync()
    expect((await pending).default).toBe(Page)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('gives up after the second failure, so the error boundary can offer a reload (the chunk is gone after a deploy)', async () => {
    const load = vi.fn().mockRejectedValue(new Error('Failed to fetch dynamically imported module'))
    const pending = runLoader(lazyNamed(load, 'Page'))
    const assertion = expect(pending).rejects.toThrow('Failed to fetch dynamically imported module')
    await vi.runAllTimersAsync()
    await assertion
    expect(load).toHaveBeenCalledTimes(2)
  })
})
