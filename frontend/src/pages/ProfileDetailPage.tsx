import {Box, Button, Text} from '@primer/react'
import {ArrowLeftIcon, DownloadIcon, UnlockIcon, VersionsIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import type {ReactNode} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, useParams} from 'react-router-dom'
import {ApiError} from '../api/client'
import {
  downloadAccountBackupPersistent,
  downloadAccountCurrentPersistent,
  getAccountCurrentPersistent,
  getAccountProfile,
  listAccountBackups,
  releaseAccountProfileLock,
  restoreAccountBackup,
} from '../api/profileKeysApi'
import type {Backup, Profile, Version} from '../api/types'
import {ByteSize} from '../components/ByteSize'
import {ConfirmDialog} from '../components/ConfirmDialog'
import {CopyableSecret} from '../components/CopyableSecret'
import {EmptyState} from '../components/EmptyState'
import {ErrorBanner} from '../components/ErrorBanner'
import {LoadingState} from '../components/LoadingState'
import {RelativeTime} from '../components/RelativeTime'
import {StorageUsageBar} from '../components/StorageUsageBar'
import {StatusLabel} from '../components/StatusLabel'

export function ProfileDetailPage() {
  const {t} = useTranslation()
  const {profileId} = useParams()
  const numericProfileId = Number(profileId)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [current, setCurrent] = useState<Version | null>(null)
  const [backups, setBackups] = useState<Backup[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [downloadingId, setDownloadingId] = useState<number | 'current' | null>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [isUnlockConfirmOpen, setIsUnlockConfirmOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    if (!Number.isFinite(numericProfileId)) {
      setError(t('account.profileDetail.invalidProfileId'))
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    Promise.all([
      getAccountProfile(numericProfileId),
      getOptionalCurrentPersistent(numericProfileId),
      listAccountBackups(numericProfileId),
    ])
      .then(([profileResponse, currentVersion, backupResponse]) => {
        if (!cancelled) {
          setProfile(profileResponse.profile)
          setCurrent(currentVersion)
          setBackups(backupResponse.items)
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setError(profileLoadErrorMessage(error, t))
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
  }, [numericProfileId])

  async function handleDownloadCurrent() {
    if (!profile) return
    setDownloadingId('current')
    try {
      saveBlob(await downloadAccountCurrentPersistent(profile.id), `profile-${profile.id}-persistent.bin`)
    } finally {
      setDownloadingId(null)
    }
  }

  async function handleDownloadBackup(backup: Backup) {
    if (!profile) return
    setDownloadingId(backup.id)
    try {
      saveBlob(await downloadAccountBackupPersistent(profile.id, backup.id), `profile-${profile.id}-backup-${backup.id}.bin`)
    } finally {
      setDownloadingId(null)
    }
  }

  async function handleRestoreBackup(backup: Backup) {
    if (!profile) return
    setIsBusy(true)
    setError(null)
    try {
      setCurrent(await restoreAccountBackup(profile.id, backup.id))
    } catch {
      setError(t('account.profileDetail.restoreError'))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleReleaseLock() {
    if (!profile) return
    setIsBusy(true)
    setError(null)
    try {
      await releaseAccountProfileLock(profile.id)
      setProfile((currentProfile) => (currentProfile ? {...currentProfile, lock_status: 'none'} : currentProfile))
      setIsUnlockConfirmOpen(false)
    } catch {
      setError(t('account.profileDetail.releaseLockError'))
    } finally {
      setIsBusy(false)
    }
  }

  const lockLabelStatus = profile?.lock_status === 'active' ? 'locked' : 'unlocked'

  return (
    <Box className="page-stack">
      {error ? <ErrorBanner message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && profile ? (
        <>
          <Box className="page-heading">
            <Box>
              <Button as={Link} to="/account/profile-keys" leadingVisual={ArrowLeftIcon} size="small">
                {t('account.profileDetail.backToKeys')}
              </Button>
              <Text as="h1" sx={{mt: 3}}>
                {profile.display_name || t('account.profileDetail.profileTitle', {id: profile.id})}
              </Text>
              <Text as="p">
                {t('account.profileDetail.profileId', {id: profile.id})} · {t('account.profileDetail.created')}{' '}
                <RelativeTime value={profile.created_at} /> · {t('account.profileDetail.lastUpload')}{' '}
                <RelativeTime value={profile.last_upload_at} />
              </Text>
            </Box>
            <StatusLabel status={profile.revoked_at ? 'revoked' : 'active'} />
          </Box>

          <Box className="panel">
            <Text as="h2" sx={{fontSize: 2, mt: 0}}>
              {t('account.profileDetail.profileKey')}
            </Text>
            <CopyableSecret value={profile.profile_key} />
            <Box className="meta-line">
              {t('account.profileDetail.lastUsed')} <RelativeTime value={profile.last_used_at} />
            </Box>
            <Box className="info-grid" sx={{mt: 3}}>
              <Info label={t('account.profileDetail.profileFileSize')} value={<ByteSize value={profile.storage_usage} />} />
            </Box>
            <StorageUsageBar usage={profile.storage_usage} limit={profile.storage_limit} />
          </Box>

          <Box className="panel">
            <Box className="section-heading">
              <Box>
                <Text as="h2" sx={{fontSize: 2, mt: 0, mb: 1}}>
                  {t('account.profileDetail.currentPersistent')}
                </Text>
                {current ? (
                  <Text as="p" sx={{color: 'fg.muted', m: 0}}>
                    {t('account.profileDetail.versionUploaded', {id: current.id})} <RelativeTime value={current.created_at} />
                  </Text>
                ) : null}
              </Box>
              <Box sx={{display: 'flex', gap: 2, flexWrap: 'wrap'}}>
                {profile.lock_status === 'active' ? (
                  <Button type="button" leadingVisual={UnlockIcon} onClick={() => setIsUnlockConfirmOpen(true)}>
                    {t('account.profileDetail.unlock')}
                  </Button>
                ) : null}
                {current ? (
                  <Button type="button" leadingVisual={DownloadIcon} onClick={handleDownloadCurrent} disabled={downloadingId === 'current'}>
                    {t('account.profileDetail.downloadCurrent')}
                  </Button>
                ) : null}
              </Box>
            </Box>
            {current ? (
              <Box className="info-grid">
                <Info label={t('account.profileDetail.size')} value={<ByteSize value={current.size} />} />
                <Info label={t('account.profileDetail.lockStatus')} value={<StatusLabel status={lockLabelStatus} />} />
                <Info label="Ren'Py" value={current.renpy_version || t('account.profileDetail.unknown')} />
                <Info label="MAS" value={current.mas_version || t('account.profileDetail.unknown')} />
              </Box>
            ) : (
              <Box className="empty-inline">
                <Text as="strong">{t('account.profileDetail.noCurrentTitle')}</Text>
                <Text as="p">{t('account.profileDetail.noCurrentMessage')}</Text>
              </Box>
            )}
          </Box>

          <Box className="table-panel">
            <Box className="table-heading">
              <Box>
                <Text as="h2" sx={{fontSize: 2, mt: 0, mb: 1}}>
                  {t('account.profileDetail.dailyBackups')}
                </Text>
                <Text as="p" sx={{color: 'fg.muted', m: 0}}>
                  {t('account.profileDetail.retainedBackups', {count: backups.length})}
                </Text>
              </Box>
            </Box>
            {backups.length === 0 ? (
              <EmptyState title={t('account.profileDetail.noBackupsTitle')} message={t('account.profileDetail.noBackupsMessage')} />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>{t('account.profileDetail.date')}</th>
                    <th>{t('account.profileDetail.size')}</th>
                    <th>SHA-256</th>
                    <th>{t('account.profileDetail.createdColumn')}</th>
                    <th>{t('account.profileDetail.action')}</th>
                  </tr>
                </thead>
                <tbody>
                  {backups.map((backup) => (
                    <tr key={backup.id}>
                      <td>
                        <VersionsIcon size={16} /> {backup.backup_date}
                      </td>
                      <td>
                        <ByteSize value={backup.size} />
                      </td>
                      <td>
                        <code className="truncate">{backup.sha256}</code>
                      </td>
                      <td>
                        <RelativeTime value={backup.created_at} />
                      </td>
                      <td>
                        <Box sx={{display: 'flex', gap: 2, flexWrap: 'wrap'}}>
                          <Button
                            type="button"
                            size="small"
                            leadingVisual={DownloadIcon}
                            aria-label={t('account.profileDetail.downloadBackup', {date: backup.backup_date})}
                            onClick={() => handleDownloadBackup(backup)}
                            disabled={downloadingId === backup.id}
                          >
                            {t('account.profileDetail.download')}
                          </Button>
                          <Button
                            type="button"
                            size="small"
                            variant="danger"
                            aria-label={t('account.profileDetail.restoreBackup', {date: backup.backup_date})}
                            onClick={() => handleRestoreBackup(backup)}
                            disabled={isBusy}
                          >
                            {t('account.profileDetail.restore')}
                          </Button>
                        </Box>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Box>
        </>
      ) : null}
      {isUnlockConfirmOpen ? (
        <ConfirmDialog
          title={t('account.profileDetail.releaseLockTitle')}
          message={t('account.profileDetail.releaseLockMessage')}
          confirmText={t('account.profileDetail.unlock')}
          variant="primary"
          onConfirm={handleReleaseLock}
          onCancel={() => setIsUnlockConfirmOpen(false)}
          isBusy={isBusy}
        />
      ) : null}
    </Box>
  )
}

async function getOptionalCurrentPersistent(profileId: number): Promise<Version | null> {
  try {
    return await getAccountCurrentPersistent(profileId)
  } catch (error) {
    if (error instanceof ApiError && error.code === 'no_current_persistent') {
      return null
    }
    throw error
  }
}

function profileLoadErrorMessage(error: unknown, t: (key: string) => string) {
  if (error instanceof ApiError) {
    if (error.code === 'profile_not_found') {
      return t('account.profileDetail.notFound')
    }
    if (error.code === 'not_authenticated') {
      return t('account.profileDetail.signInAgain')
    }
  }
  return t('account.profileDetail.loadError')
}

function Info({label, value}: {label: string; value: ReactNode}) {
  return (
    <Box className="info-cell">
      <span>{label}</span>
      <strong>{value}</strong>
    </Box>
  )
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
