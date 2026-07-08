import {Box, Button, Text} from '@primer/react'
import {DatabaseIcon} from '@primer/octicons-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'
import {ApiError} from '../api/client'
import {useAuth} from '../auth/AuthProvider'
import {ErrorBanner} from '../components/ErrorBanner'

export function LoginPage() {
  const {t} = useTranslation()
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
        setError(t('login.invalidCredentials'))
      } else {
        setError(t('login.genericError'))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Box className="login-page">
      <Box className="login-card">
        <Box className="login-brand">
          <span className="brand-mark" aria-hidden="true">
            <DatabaseIcon size={18} />
          </span>
          <Text as="h1" sx={{fontSize: 4, m: 0}}>
            MAS UniSync
          </Text>
        </Box>
        <Text as="p" sx={{color: 'fg.muted', mt: 0, mb: 3}}>
          {t('login.intro')}
        </Text>
        {error ? <ErrorBanner title={t('login.failedTitle')} message={error} /> : null}
        <form onSubmit={handleSubmit} className="stack">
          <label className="field">
            <span>{t('login.accountLabel')}</span>
            <input value={identification} onChange={(event) => setIdentification(event.target.value)} required autoComplete="username" />
          </label>
          <label className="field">
            <span>{t('login.passwordLabel')}</span>
            <input value={password} onChange={(event) => setPassword(event.target.value)} required type="password" autoComplete="current-password" />
          </label>
          <Button type="submit" variant="primary" disabled={isSubmitting || !identification || !password}>
            {t('login.submit')}
          </Button>
        </form>
      </Box>
    </Box>
  )
}
