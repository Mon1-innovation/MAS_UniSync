import {Box, Button, Text} from '@primer/react'
import {CheckIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {getAdminSettings, updateAdminSettings} from '../../api/adminApi'
import type {SystemSettings} from '../../api/types'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'

const emptySettings: SystemSettings = {
  backend_api_url: '',
  frontend_web_url: '',
  profile_storage_limit_bytes: 10 * 1024 * 1024,
  max_active_profiles_per_account: 3,
}

export function AdminSettingsPage() {
  const [settings, setSettings] = useState<SystemSettings>(emptySettings)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedMessage, setSavedMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    getAdminSettings()
      .then((response) => {
        if (!cancelled) {
          setSettings(response.settings)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Could not load system settings.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSaving(true)
    setError(null)
    setSavedMessage('')
    try {
      const response = await updateAdminSettings(settings)
      setSettings(response.settings)
      setSavedMessage('Settings saved.')
    } catch {
      setError('Could not save system settings.')
    } finally {
      setIsSaving(false)
    }
  }

  function updateField<K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) {
    setSettings((current) => ({...current, [key]: value}))
  }

  return (
    <Box className="page-stack">
      <Box className="page-heading">
        <Box>
          <Text as="h1">Settings</Text>
          <Text as="p">Configure runtime URLs and account limits.</Text>
        </Box>
      </Box>

      {error ? <ErrorBanner message={error} /> : null}
      {savedMessage ? (
        <Box className="success-banner">
          <CheckIcon size={16} />
          <span>{savedMessage}</span>
        </Box>
      ) : null}
      {isLoading ? <LoadingState /> : null}

      {!isLoading ? (
        <form onSubmit={handleSubmit}>
          <Box className="panel settings-form">
            <label className="field">
              <span>Backend API URL</span>
              <input
                value={settings.backend_api_url}
                onChange={(event) => updateField('backend_api_url', event.target.value)}
                placeholder="https://api.example.com"
              />
            </label>
            <label className="field">
              <span>Frontend web URL</span>
              <input
                value={settings.frontend_web_url}
                onChange={(event) => updateField('frontend_web_url', event.target.value)}
                placeholder="https://portal.example.com"
              />
            </label>
            <label className="field">
              <span>Profile storage limit bytes</span>
              <input
                type="number"
                min={1}
                step={1}
                value={settings.profile_storage_limit_bytes}
                onChange={(event) => updateField('profile_storage_limit_bytes', Number(event.target.value))}
              />
            </label>
            <label className="field">
              <span>Max active profiles per account</span>
              <input
                type="number"
                min={1}
                step={1}
                value={settings.max_active_profiles_per_account}
                onChange={(event) => updateField('max_active_profiles_per_account', Number(event.target.value))}
              />
            </label>
            <Box>
              <Button type="submit" variant="primary" disabled={isSaving}>
                Save settings
              </Button>
            </Box>
          </Box>
        </form>
      ) : null}
    </Box>
  )
}
