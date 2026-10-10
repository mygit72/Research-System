import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/Feedback'
import { Field } from '@/components/ui/Input'
import { ApiError } from '@/services/http'
import { useAuth } from '@/stores/auth'
import { AuthLayout } from './AuthLayout'

export function RegisterPage() {
  const register = useAuth((s) => s.register)
  const navigate = useNavigate()
  const [form, setForm] = useState({ fullName: '', email: '', password: '' })
  const [error, setError] = useState<unknown>(null)
  const [pending, setPending] = useState(false)

  const fieldErrors = error instanceof ApiError ? error.fieldErrors : {}
  const update = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await register(form.email, form.password, form.fullName)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setPending(false)
    }
  }

  const hasFieldErrors = Object.keys(fieldErrors).length > 0

  return (
    <AuthLayout
      title="Create your workspace"
      subtitle="Search, understand and compare your research papers with AI."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && !hasFieldErrors ? (
          <ErrorState error={error} title="Couldn't create your account" />
        ) : null}
        <Field
          label="Name"
          autoComplete="name"
          value={form.fullName}
          onChange={update('fullName')}
          error={fieldErrors.full_name}
          autoFocus
        />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={update('email')}
          error={fieldErrors.email}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          value={form.password}
          onChange={update('password')}
          error={fieldErrors.password}
          description="At least 10 characters, mixing letters with numbers or symbols."
        />
        <Button type="submit" size="lg" className="w-full justify-center" loading={pending}>
          Create account
        </Button>
      </form>
    </AuthLayout>
  )
}
