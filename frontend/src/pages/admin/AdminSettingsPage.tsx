import {Box, Button, Text} from '@primer/react'
import {BeakerIcon, CheckIcon, InfoIcon, PlusIcon, TrashIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {deleteStorageBucket, getAdminSettings, getStorageBucketUsage, testStorageBucket, updateAdminSettings} from '../../api/adminApi'
import {ApiError} from '../../api/client'
import type {StorageBucket, StorageBucketUsage, SystemSettings} from '../../api/types'
import {ByteSize} from '../../components/ByteSize'
import {ConfirmDialog} from '../../components/ConfirmDialog'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'

const emptySettings: SystemSettings = {
  backend_api_url: '',
  frontend_web_url: '',
  profile_storage_limit_bytes: 10 * 1024 * 1024,
  max_active_profiles_per_account: 3,
  guest_key_retention_days: 360,
  active_storage_bucket_id: null,
  storage_buckets: [],
}

function normalizeSettings(settings: SystemSettings): SystemSettings {
  const storageBuckets = settings.storage_buckets ?? []
  return {
    ...settings,
    guest_key_retention_days: settings.guest_key_retention_days ?? 360,
    active_storage_bucket_id: settings.active_storage_bucket_id ?? storageBuckets.find((bucket) => bucket.is_active)?.id ?? null,
    storage_buckets: storageBuckets.map((bucket) => ({
      ...bucket,
      space_budget_bytes: bucket.space_budget_bytes ?? null,
      usage_summary: bucket.usage_summary ?? null,
      is_config_locked: Boolean(bucket.is_config_locked),
      config: {
        ...bucket.config,
        password: bucket.config.password ?? '',
      },
    })),
  }
}

function settingsPayload(settings: SystemSettings): SystemSettings {
  return {
    ...settings,
    storage_buckets: settings.storage_buckets.map((bucket) => ({
      ...bucket,
      config:
        bucket.type === 'webdav'
          ? {...bucket.config, password: bucket.config.password ?? ''}
          : {...bucket.config},
    })),
  }
}

export function AdminSettingsPage() {
  const {t} = useTranslation()
  const [settings, setSettings] = useState<SystemSettings>(emptySettings)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedMessage, setSavedMessage] = useState('')
  const [testingBucketIndex, setTestingBucketIndex] = useState<number | null>(null)
  const [loadingUsageBucketIndex, setLoadingUsageBucketIndex] = useState<number | null>(null)
  const [usageByBucketId, setUsageByBucketId] = useState<Record<number, StorageBucketUsage>>({})
  const [deleteBucketIndex, setDeleteBucketIndex] = useState<number | null>(null)
  const [isDeletingBucket, setIsDeletingBucket] = useState(false)

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
      const response = await updateAdminSettings(settingsPayload({
        ...settings,
        active_storage_bucket_id: activeBucket?.id ?? null,
      }))
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
          space_budget_bytes: null,
          usage_summary: null,
          is_config_locked: false,
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
    if (!bucket || (bucket.type === 'local' && bucket.name === 'Docker local storage')) {
      return
    }
    setDeleteBucketIndex(index)
  }

  async function confirmRemoveBucket() {
    if (deleteBucketIndex === null) {
      return
    }
    const bucket = settings.storage_buckets[deleteBucketIndex]
    if (!bucket) {
      setDeleteBucketIndex(null)
      return
    }
    setIsDeletingBucket(true)
    setError(null)
    try {
      if (bucket.id) {
        await deleteStorageBucket(bucket.id)
      }
      setSettings((current) => ({
        ...current,
        storage_buckets: current.storage_buckets.filter((_, bucketIndex) => bucketIndex !== deleteBucketIndex),
      }))
      setDeleteBucketIndex(null)
    } catch (caught) {
      setError(apiErrorMessage(caught, t('admin.settings.deleteBucketError')))
    } finally {
      setIsDeletingBucket(false)
    }
  }

  async function loadBucketUsage(index: number) {
    const bucket = settings.storage_buckets[index]
    if (!bucket?.id) {
      return
    }
    setError(null)
    setLoadingUsageBucketIndex(index)
    try {
      const usage = await getStorageBucketUsage(bucket.id)
      setUsageByBucketId((current) => ({...current, [bucket.id as number]: usage}))
      updateBucket(index, {
        usage_summary: {
          file_count: usage.file_count,
          total_size: usage.total_size,
          backup_reference_count: usage.backup_reference_count,
          current_reference_count: usage.current_reference_count,
        },
        space_budget_bytes: usage.space_budget_bytes,
        is_config_locked: usage.file_count > 0,
      })
    } catch (caught) {
      setError(apiErrorMessage(caught, t('admin.settings.usageBucketError')))
    } finally {
      setLoadingUsageBucketIndex(null)
    }
  }

  async function testBucket(index: number) {
    const bucket = settings.storage_buckets[index]
    if (!bucket) {
      return
    }
    setError(null)
    setSavedMessage('')
    setTestingBucketIndex(index)
    try {
      await testStorageBucket(bucket)
      setSavedMessage(t('admin.settings.testBucketPassed'))
    } catch (caught) {
      setError(storageBucketTestErrorMessage(caught, t('admin.settings.testBucketError')))
    } finally {
      setTestingBucketIndex(null)
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
            <label className="field">
              <span>{t('admin.settings.guestKeyRetentionDays')}</span>
              <input
                type="number"
                min={1}
                step={1}
                value={settings.guest_key_retention_days}
                onChange={(event) => updateField('guest_key_retention_days', Number(event.target.value))}
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
                        <SpaceBudgetField
                          value={bucket.space_budget_bytes ?? null}
                          label={t('admin.settings.spaceBudgetBytes')}
                          onChange={(value) => updateBucket(index, {space_budget_bytes: value})}
                        />
                        <UsageSummary usage={bucket.id ? usageByBucketId[bucket.id] : undefined} t={t} />
                        <Box className="storage-bucket-actions">
                          <Button
                            type="button"
                            leadingVisual={BeakerIcon}
                            disabled={testingBucketIndex === index}
                            onClick={() => void testBucket(index)}
                          >
                            {testingBucketIndex === index ? t('admin.settings.testingBucket') : t('admin.settings.testBucket')}
                          </Button>
                          <Button
                            type="button"
                            leadingVisual={InfoIcon}
                            disabled={!bucket.id || loadingUsageBucketIndex === index}
                            onClick={() => void loadBucketUsage(index)}
                          >
                            {loadingUsageBucketIndex === index ? t('admin.settings.loadingUsage') : t('admin.settings.usageInfo')}
                          </Button>
                          <Button
                            type="button"
                            variant="danger"
                            leadingVisual={TrashIcon}
                            disabled={bucket.name === 'Docker local storage'}
                            onClick={() => void removeBucket(index)}
                          >
                            {t('admin.settings.deleteBucket')}
                          </Button>
                        </Box>
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
                            disabled={bucket.is_config_locked}
                            onChange={(event) => updateBucketConfig(index, {base_url: event.target.value})}
                            placeholder="https://dav.example.com/root"
                          />
                        </label>
                        <label className="field">
                          <span>{t('admin.settings.webDavUsername')}</span>
                          <input
                            value={bucket.config.username ?? ''}
                            disabled={bucket.is_config_locked}
                            onChange={(event) => updateBucketConfig(index, {username: event.target.value})}
                          />
                        </label>
                        <label className="field">
                          <span>{t('admin.settings.webDavPassword')}</span>
                          <input
                            type="password"
                            value={bucket.config.password ?? ''}
                            disabled={bucket.is_config_locked}
                            onChange={(event) => updateBucketConfig(index, {password: event.target.value})}
                            placeholder={bucket.config.has_password ? t('admin.settings.passwordUnchanged') : ''}
                          />
                        </label>
                        <label className="field">
                          <span>{t('admin.settings.webDavRootPath')}</span>
                          <input
                            value={bucket.config.root_path ?? ''}
                            disabled={bucket.is_config_locked}
                            onChange={(event) => updateBucketConfig(index, {root_path: event.target.value})}
                            placeholder="persistent"
                          />
                        </label>
                        <SpaceBudgetField
                          value={bucket.space_budget_bytes ?? null}
                          label={t('admin.settings.spaceBudgetBytes')}
                          onChange={(value) => updateBucket(index, {space_budget_bytes: value})}
                        />
                        <UsageSummary usage={bucket.id ? usageByBucketId[bucket.id] : undefined} t={t} />
                        <Box className="storage-bucket-actions">
                          <Button
                            type="button"
                            leadingVisual={BeakerIcon}
                            disabled={testingBucketIndex === index}
                            onClick={() => void testBucket(index)}
                          >
                            {testingBucketIndex === index ? t('admin.settings.testingBucket') : t('admin.settings.testBucket')}
                          </Button>
                          <Button
                            type="button"
                            leadingVisual={InfoIcon}
                            disabled={!bucket.id || loadingUsageBucketIndex === index}
                            onClick={() => void loadBucketUsage(index)}
                          >
                            {loadingUsageBucketIndex === index ? t('admin.settings.loadingUsage') : t('admin.settings.usageInfo')}
                          </Button>
                          <Button
                            type="button"
                            variant="danger"
                            leadingVisual={TrashIcon}
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
      {deleteBucketIndex !== null ? (
        <ConfirmDialog
          title={t('admin.settings.deleteBucketTitle')}
          message={t('admin.settings.deleteBucketMessage')}
          confirmText={t('admin.settings.deleteBucket')}
          isBusy={isDeletingBucket}
          onCancel={() => setDeleteBucketIndex(null)}
          onConfirm={confirmRemoveBucket}
        />
      ) : null}
    </Box>
  )
}

function SpaceBudgetField({
  value,
  label,
  onChange,
}: {
  value: number | null
  label: string
  onChange: (value: number | null) => void
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        min={0}
        step={1}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))}
      />
    </label>
  )
}

function UsageSummary({
  usage,
  t,
}: {
  usage: StorageBucketUsage | undefined
  t: (key: string, options?: Record<string, unknown>) => string
}) {
  if (!usage) {
    return null
  }
  return (
    <Box className="storage-bucket-usage">
      <span>{t('admin.settings.usageFiles', {count: usage.file_count})}</span>
      <span>
        {t('admin.settings.usageTotal')}: <ByteSize value={usage.total_size} />
      </span>
      <span>{t('admin.settings.usageBackups', {count: usage.backup_reference_count})}</span>
      <span>{t('admin.settings.usageCurrent', {count: usage.current_reference_count})}</span>
      <span>
        {t('admin.settings.usageBudget')}: {usage.space_budget_bytes === null ? t('admin.settings.noBudget') : <ByteSize value={usage.space_budget_bytes} />}
      </span>
    </Box>
  )
}

function storageBucketTestErrorMessage(error: unknown, fallback: string): string {
  return apiErrorMessage(error, fallback, true)
}

function apiErrorMessage(error: unknown, fallback: string, includeDiagnostics = false): string {
  if (!(error instanceof ApiError)) {
    return fallback
  }
  const detail = error.detail
  const maybeDetail = detail && typeof detail === 'object' && 'detail' in detail ? (detail as {detail?: unknown}).detail : detail
  if (!maybeDetail || typeof maybeDetail !== 'object') {
    return `${fallback} HTTP ${error.status}`
  }
  const fields = maybeDetail as Record<string, unknown>
  const parts = [
    typeof fields.code === 'string' ? fields.code : error.code,
    includeDiagnostics && typeof fields.phase === 'string' ? `phase=${fields.phase}` : '',
    includeDiagnostics && typeof fields.error_type === 'string' ? `error=${fields.error_type}` : '',
    includeDiagnostics && typeof fields.upstream_status === 'number' ? `upstream=${fields.upstream_status}` : '',
  ].filter(Boolean)
  return parts.length > 0 ? `${fallback} ${parts.join(' ')}` : `${fallback} HTTP ${error.status}`
}
