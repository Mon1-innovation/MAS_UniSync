import {Box, Button, Text} from '@primer/react'
import {DatabaseIcon} from '@primer/octicons-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'
import {ApiError} from '../api/client'
import {useAuth} from '../auth/AuthProvider'
import {ErrorBanner} from '../components/ErrorBanner'
import {LanguageSwitcher} from '../components/LanguageSwitcher'

export function LoginPage() {
  const {t} = useTranslation()
  const {login, loginGuest} = useAuth()
  const [mode, setMode] = useState<'flarum' | 'guest'>('flarum')
  const [identification, setIdentification] = useState('')
  const [password, setPassword] = useState('')
  const [profileKey, setProfileKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      if (mode === 'guest') {
        await loginGuest(profileKey.trim())
      } else {
        await login(identification, password)
      }
    } catch (caught) {
      if (mode === 'guest' && caught instanceof ApiError) {
        if (caught.code === 'invalid_profile_key') {
          setError(t('login.invalidGuestKey'))
        } else if (caught.code === 'profile_key_not_guest') {
          setError(t('login.notGuestKey'))
        } else if (caught.code === 'banned') {
          setError(t('login.bannedGuestKey'))
        } else {
          setError(t('login.genericError'))
        }
      } else if (caught instanceof ApiError && caught.status === 401) {
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
        <LanguageSwitcher className="login-language" />
        <Box className="login-brand">
          <span className="brand-mark" aria-hidden="true">
            <DatabaseIcon size={18} />
          </span>
          <Text as="h1" sx={{fontSize: 4, m: 0}}>
            MAS UniSync
          </Text>
        </Box>
        <Text as="p" sx={{color: 'fg.muted', mt: 0, mb: 3}}>
          {t(mode === 'guest' ? 'login.guestIntro' : 'login.intro')}
        </Text>
        <div className="login-mode" role="group" aria-label={t('login.modeLabel')}>
          <button type="button" className={mode === 'flarum' ? 'is-active' : undefined} aria-pressed={mode === 'flarum'} onClick={() => { setMode('flarum'); setError(null) }}>
            {t('login.flarumMode')}
          </button>
          <button type="button" className={mode === 'guest' ? 'is-active' : undefined} aria-pressed={mode === 'guest'} onClick={() => { setMode('guest'); setError(null) }}>
            {t('login.guestMode')}
          </button>
        </div>
        {error ? <ErrorBanner title={t('login.failedTitle')} message={error} /> : null}
        <form onSubmit={handleSubmit} className="stack">
          {mode === 'flarum' ? (
            <>
              <label className="field">
                <span>{t('login.accountLabel')}</span>
                <input value={identification} onChange={(event) => setIdentification(event.target.value)} required autoComplete="username" />
              </label>
              <label className="field">
                <span>{t('login.passwordLabel')}</span>
                <input value={password} onChange={(event) => setPassword(event.target.value)} required type="password" autoComplete="current-password" />
              </label>
            </>
          ) : (
            <label className="field">
              <span>{t('login.profileKeyLabel')}</span>
              <input value={profileKey} onChange={(event) => setProfileKey(event.target.value)} required autoComplete="off" />
            </label>
          )}
          <Button type="submit" variant="primary" disabled={isSubmitting || (mode === 'guest' ? !profileKey.trim() : !identification || !password)}>
            {t(mode === 'guest' ? 'login.guestSubmit' : 'login.submit')}
          </Button>
        </form>
      </Box>
    </Box>
  )
}
