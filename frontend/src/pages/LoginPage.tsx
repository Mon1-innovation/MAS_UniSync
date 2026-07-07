import {Box, Button, Text} from '@primer/react'
import {useState} from 'react'
import {ApiError} from '../api/client'
import {useAuth} from '../auth/AuthProvider'
import {ErrorBanner} from '../components/ErrorBanner'

export function LoginPage() {
  const {login} = useAuth()
  const [identification, setIdentification] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login(identification, password)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setError('Flarum credentials are invalid.')
      } else {
        setError('Unable to sign in. Please try again.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Box className="login-page">
      <Box className="login-card">
        <Text as="h1" sx={{fontSize: 4, mb: 1}}>
          MAS UniSync
        </Text>
        <Text as="p" sx={{color: 'fg.muted', mt: 0, mb: 3}}>
          Sign in with your Flarum account.
        </Text>
        {error ? <ErrorBanner title="Sign in failed" message={error} /> : null}
        <form onSubmit={handleSubmit} className="stack">
          <label className="field">
            <span>Flarum account or email</span>
            <input value={identification} onChange={(event) => setIdentification(event.target.value)} required autoComplete="username" />
          </label>
          <label className="field">
            <span>Password</span>
            <input value={password} onChange={(event) => setPassword(event.target.value)} required type="password" autoComplete="current-password" />
          </label>
          <Button type="submit" variant="primary" disabled={isSubmitting || !identification || !password}>
            Sign in
          </Button>
        </form>
      </Box>
    </Box>
  )
}
