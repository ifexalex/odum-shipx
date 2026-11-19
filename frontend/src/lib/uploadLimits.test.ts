import { describe, expect, it } from 'vitest'
import { MAX_UPLOAD_BYTES, uploadSizeProblem } from './uploadLimits'

const sized = (bytes: number): File => {
  const file = new File(['x'], 'f.pdf', { type: 'application/pdf' })
  Object.defineProperty(file, 'size', { value: bytes })
  return file
}

describe('upload size limit (5 MB, the API limit)', () => {
  it('is 5 MB', () => expect(MAX_UPLOAD_BYTES).toBe(5 * 1024 * 1024))
  it('accepts exactly the limit', () => expect(uploadSizeProblem(sized(MAX_UPLOAD_BYTES))).toBeNull())
  it('refuses one byte over, saying the size and the limit', () =>
    expect(uploadSizeProblem(sized(MAX_UPLOAD_BYTES + 1))).toBe('This file is 5.0 MB. The limit is 5 MB.'))
  it('refuses an empty file', () => expect(uploadSizeProblem(sized(0))).toMatch(/empty/))
})
