import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          'h-10 w-full rounded-md border border-border bg-surface px-3 text-body text-text',
          'placeholder:text-subtle transition-colors',
          'hover:border-border-strong focus-visible:border-primary focus-visible:outline-none',
          'focus-visible:ring-3 focus-visible:ring-primary/20',
          'aria-[invalid=true]:border-error aria-[invalid=true]:focus-visible:ring-error/20',
          'disabled:cursor-not-allowed disabled:opacity-60',
          className,
        )}
        {...props}
      />
    )
  },
)

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string
  description?: ReactNode
}

/** Labelled input with accessible description/error wiring. */
export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, error, description, id, ...props },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const hintId = `${inputId}-hint`
  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="block text-small font-medium text-text">
        {label}
      </label>
      <Input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || description ? hintId : undefined}
        {...props}
      />
      {(error || description) && (
        <p id={hintId} className={cn('text-caption', error ? 'text-error' : 'text-muted')}>
          {error ?? description}
        </p>
      )}
    </div>
  )
})
