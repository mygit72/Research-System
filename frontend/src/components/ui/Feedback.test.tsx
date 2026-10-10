import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BookOpen } from 'lucide-react'
import { describe, expect, it, vi } from 'vitest'
import { initials } from '@/lib/format'
import { ApiError } from '@/services/http'
import { EmptyState, ErrorState, ProgressBar } from './Feedback'

describe('EmptyState', () => {
  it('teaches the next step', () => {
    render(
      <EmptyState
        icon={BookOpen}
        title="Your research library is empty."
        description="Upload your first paper."
        actions={<button>Upload Paper</button>}
      />,
    )
    expect(screen.getByRole('heading', { name: 'Your research library is empty.' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload Paper' })).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('shows what happened, the hint, a reference, and a retry action', async () => {
    const onRetry = vi.fn()
    const error = new ApiError(422, {
      code: 'bad',
      message: "We couldn't process this PDF.",
      hint: 'The file may be password-protected.',
      request_id: 'abc123',
    })
    render(<ErrorState error={error} onRetry={onRetry} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent("We couldn't process this PDF.")
    expect(alert).toHaveTextContent('password-protected')
    expect(alert).toHaveTextContent('abc123')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

describe('ProgressBar', () => {
  it('is accessible and clamps its value', () => {
    render(<ProgressBar value={1.7} label="Upload" />)
    expect(screen.getByRole('progressbar', { name: 'Upload' })).toHaveAttribute('aria-valuenow', '100')
  })
})

describe('initials', () => {
  it('derives initials from name or email', () => {
    expect(initials('Ada Lovelace', 'a@b.c')).toBe('AL')
    expect(initials('', 'grace.hopper@navy.mil')).toBe('GH')
  })
})
