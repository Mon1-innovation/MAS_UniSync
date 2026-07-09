import {Box, Button, Text} from '@primer/react'
import {CheckIcon, PlusIcon, TrashIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {deleteStorageBucket, getAdminSettings, updateAdminSettings} from '../../api/adminApi'
import type {StorageBucket, SystemSettings} from '../../api/types'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'

const emptySettings: SystemSettings = {
  backend_api_url: '',
  frontend_web_url: '',
  profile_storage_limit_bytes: 10 * 1024 * 1024,
  max_active_profiles_per_account: 3,
  active_storage_bucket_id: null,
  storage_buckets: [],
}

function normalizeSettings(settings: SystemSettings): SystemSettings {
  const storageBuckets = settings.storage_buckets ?? []
  return {
    ...settings,
    active_storage_bucket_id: settings.active_storage_bucket_id ?? storageBuckets.find((bucket) => bucket.is_active)?.id ?? null,
    storage_buckets: storageBuckets,
  }
}

export function AdminSettingsPage() {
  const {t} = useTranslation()
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
          setSettings(normalizeSettings(response.settings))
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(t('admin.settings.loadError'))
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
  }, [t])

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSaving(true)
    setError(null)
    setSavedMessage('')
    try {
      const activeBucket = settings.storage_buckets.find((bucket) => bucket.is_active)
      const response = await updateAdminSettings({
        ...settings,
        active_storage_bucket_id: activeBucket?.id ?? null,
      })
      setSettings(normalizeSettings(response.settings))
      setSavedMessage(t('admin.settings.saved'))
    } catch {
      setError(t('admin.settings.saveError'))
    } finally {
      setIsSaving(false)
    }
  }

  function updateField<K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) {
    setSettings((current) => ({...current, [key]: value}))
  }

  function addWebDavBucket() {
    setSettings((current) => ({
      ...current,
      storage_buckets: [
        ...current.storage_buckets,
        {
          name: 'WebDAV',
          type: 'webdav',
          is_active: false,
          config: {base_url: '', username: '', password: '', root_path: ''},
        },
      ],
    }))
  }

  function updateBucket(index: number, patch: Partial<StorageBucket>) {
    setSettings((current) => ({
      ...current,
      storage_buckets: current.storage_buckets.map((bucket, bucketIndex) =>
        bucketIndex === index ? {...bucket, ...patch} : bucket,
      ),
    }))
  }

  function updateBucketConfig(index: number, patch: StorageBucket['config']) {
    setSettings((current) => ({
      ...current,
      storage_buckets: current.storage_buckets.map((bucket, bucketIndex) =>
        bucketIndex === index ? {...bucket, config: {...bucket.config, ...patch}} : bucket,
      ),
    }))
  }

  function markActiveBucket(index: number) {
    setSettings((current) => {
      const nextBuckets = current.storage_buckets.map((bucket, bucketIndex) => ({
        ...bucket,
        is_active: bucketIndex === index,
      }))
      return {
        ...current,
        active_storage_bucket_id: nextBuckets[index]?.id ?? null,
        storage_buckets: nextBuckets,
      }
    })
  }

  async function removeBucket(index: number) {
    const bucket = settings.storage_buckets[index]
    if (!bucket || bucket.type === 'local' || bucket.is_active) {
      return
    }
    setError(null)
    try {
      if (bucket.id) {
        await deleteStorageBucket(bucket.id)
      }
      setSettings((current) => ({
        ...current,
        storage_buckets: current.storage_buckets.filter((_, bucketIndex) => bucketIndex !== index),
      }))
    } catch {
      setError(t('admin.settings.deleteBucketError'))
    }
  }

  return (
    <Box className="page-stack">
      <Box className="page-heading">
        <Box>
          <Text as="h1">{t('admin.settings.title')}</Text>
          <Text as="p">{t('admin.settings.description')}</Text>
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
              <span>{t('admin.settings.backendApiUrl')}</span>
              <input
                value={settings.backend_api_url}
                onChange={(event) => updateField('backend_api_url', event.target.value)}
                placeholder="https://api.example.com"
              />
            </label>
            <label className="field">
              <span>{t('admin.settings.frontendWebUrl')}</span>
              <input
                value={settings.frontend_web_url}
                onChange={(event) => updateField('frontend_web_url', event.target.value)}
                placeholder="https://portal.example.com"
              />
            </label>
            <label className="field">
              <span>{t('admin.settings.profileStorageLimitBytes')}</span>
              <input
                type="number"
                min={1}
                step={1}
                value={settings.profile_storage_limit_bytes}
                onChange={(event) => updateField('profile_storage_limit_bytes', Number(event.target.value))}
              />
            </label>
            <label className="field">
              <span>{t('admin.settings.maxActiveProfiles')}</span>
              <input
                type="number"
                min={1}
                step={1}
                value={settings.max_active_profiles_per_account}
                onChange={(event) => updateField('max_active_profiles_per_account', Number(event.target.value))}
              />
            </label>
            <Box className="settings-section">
              <Box className="settings-section-header">
                <Box>
                  <Text as="h2">{t('admin.settings.storageBuckets')}</Text>
                  <Text as="p">{t('admin.settings.storageBucketsDescription')}</Text>
                </Box>
                <Button type="button" leadingVisual={PlusIcon} onClick={addWebDavBucket}>
                  {t('admin.settings.addWebDavBucket')}
                </Button>
              </Box>
              <Box className="storage-bucket-list">
                {settings.storage_buckets.map((bucket, index) => (
                  <Box className="storage-bucket-item" key={bucket.id ?? `new-${index}`}>
                    <Box className="storage-bucket-title">
                      <label className="radio-row">
                        <input
                          type="radio"
                          name="active-storage-bucket"
                          checked={bucket.is_active}
                          onChange={() => markActiveBucket(index)}
                          aria-label={t('admin.settings.useBucketAsActive', {name: bucket.name || t('admin.settings.newBucket')})}
                        />
                        <span>{bucket.name || t('admin.settings.newBucket')}</span>
                      </label>
                      <span className="status-pill">{bucket.type}</span>
                      {bucket.is_active ? <span className="status-pill is-active">{t('admin.settings.activeBucket')}</span> : null}
                    </Box>
                    {bucket.type === 'local' ? (
                      <Box className="storage-bucket-readonly">
                        <span>{t('admin.settings.localPath')}</span>
                        <code>{bucket.config.path}</code>
                      </Box>
                    ) : (
                      <Box className="storage-bucket-fields">
                        <label className="field">
                          <span>{t('admin.settings.bucketName')}</span>
                          <input
                            value={bucket.name}
                            onChange={(event) => updateBucket(index, {name: event.target.value})}
                          />
                        </label>
                        <label className="field">
                          <span>{t('admin.settings.webDavUrl')}</span>
                          <input
                            value={bucket.config.base_url ?? ''}
                            onChange={(event) => updateBucketConfig(index, {base_url: event.target.value})}
                            placeholder="https://dav.example.com/root"
                          />
                        </label>
                        <label className="field">
                          <span>{t('admin.settings.webDavUsername')}</span>
                          <input
                            value={bucket.config.username ?? ''}
                            onChange={(event) => updateBucketConfig(index, {username: event.target.value})}
                          />
                        </label>
                        <label className="field">
                          <span>{t('admin.settings.webDavPassword')}</span>
                          <input
                            type="password"
                            value={bucket.config.password ?? ''}
                            onChange={(event) => updateBucketConfig(index, {password: event.target.value})}
                            placeholder={bucket.config.has_password ? t('admin.settings.passwordUnchanged') : ''}
                          />
                        </label>
                        <label className="field">
                          <span>{t('admin.settings.webDavRootPath')}</span>
                          <input
                            value={bucket.config.root_path ?? ''}
                            onChange={(event) => updateBucketConfig(index, {root_path: event.target.value})}
                            placeholder="persistent"
                          />
                        </label>
                        <Box className="storage-bucket-actions">
                          <Button
                            type="button"
                            variant="danger"
                            leadingVisual={TrashIcon}
                            disabled={bucket.is_active}
                            onClick={() => void removeBucket(index)}
                          >
                            {t('admin.settings.deleteBucket')}
                          </Button>
                        </Box>
                      </Box>
                    )}
                  </Box>
                ))}
              </Box>
            </Box>
            <Box>
              <Button type="submit" variant="primary" disabled={isSaving}>
                {t('admin.settings.save')}
              </Button>
            </Box>
          </Box>
        </form>
      ) : null}
    </Box>
  )
}
