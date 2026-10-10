import { describe, expect, it } from 'vitest'
import { cn } from './cn'

describe('cn', () => {
  it('keeps custom type-scale classes alongside text colors', () => {
    expect(cn('text-primary-fg', 'text-small')).toBe('text-primary-fg text-small')
    expect(cn('text-h3 text-text')).toBe('text-h3 text-text')
  })

  it('still resolves real conflicts', () => {
    expect(cn('text-small', 'text-body')).toBe('text-body')
    expect(cn('text-muted', 'text-text')).toBe('text-text')
  })
})
