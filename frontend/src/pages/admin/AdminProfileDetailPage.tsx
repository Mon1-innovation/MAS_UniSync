import {Box, Button, Text} from '@primer/react'
import {BlockedIcon, DownloadIcon, ShieldCheckIcon, SyncIcon, TrashIcon, UnlockIcon, VersionsIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import type {ReactNode} from 'react'
import type {TFunction} from 'i18next'
import {useTranslation} from 'react-i18next'
import {useNavigate, useParams} from 'react-router-dom'
import {ApiError} from '../../api/client'
import {
  banProfile,
  banProfileKey,
  deleteAdminProfileKey,
  downloadBackupPersistent,
  downloadCurrentPersistent,
  getAdminCurrentPersistent,
  getAdminProfile,
  listAdminBackups,
  refreshAdminProfileKey,
  releaseAdminLock,
  restoreAdminBackup,
  unbanProfile,
  unbanProfileKey,
} from '../../api/adminApi'
import type {Backup, Profile, Version} from '../../api/types'
import {ByteSize} from '../../components/ByteSize'
import {ConfirmDialog} from '../../components/ConfirmDialog'
import {CopyableSecret} from '../../components/CopyableSecret'
import {EmptyState} from '../../components/EmptyState'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'
import {RelativeTime} from '../../components/RelativeTime'
import {StorageUsageBar} from '../../components/StorageUsageBar'
import {StatusLabel} from '../../components/StatusLabel'

type PendingAction = 'banProfile' | 'unbanProfile' | 'banKey' | 'unbanKey' | 'refreshKey' | 'deleteKey' | 'releaseLock' | null

export function AdminProfileDetailPage() {
  const {t} = useTranslation()
  const {profileId} = useParams()
  const navigate = useNavigate()
  const numericProfileId = Number(profileId)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [current, setCurrent] = useState<Version | null>(null)
  const [backups, setBackups] = useState<Backup[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [downloadingId, setDownloadingId] = useState<number | 'current' | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    if (!Number.isFinite(numericProfileId)) {
      setError(t('admin.profileDetail.invalidProfileId'))
      return
    }
    Promise.all([
      getAdminProfile(numericProfileId),
      getOptionalAdminCurrentPersistent(numericProfileId),
      listAdminBackups(numericProfileId),
    ])
      .then(([profileResponse, currentVersion, backupResponse]) => {
        if (!cancelled) {
          setProfile(profileResponse.profile)
          setCurrent(currentVersion)
          setBackups(backupResponse.items)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(t('admin.profileDetail.loadError'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [numericProfileId, t])

  async function handleConfirm() {
    if (!profile || !pendingAction) {
      return
    }
    const actionType = pendingAction
    setIsBusy(true)
    setError(null)
    try {
      if (pendingAction === 'banProfile') await banProfile(profile.id)
      if (pendingAction === 'unbanProfile') await unbanProfile(profile.id)
      if (pendingAction === 'banKey') await banProfileKey(profile.id)
      if (pendingAction === 'unbanKey') await unbanProfileKey(profile.id)
      if (pendingAction === 'releaseLock') await releaseAdminLock(profile.id)
      if (pendingAction === 'refreshKey') setProfile(await refreshAdminProfileKey(profile.id))
      if (pendingAction === 'deleteKey') {
        await deleteAdminProfileKey(profile.id)
        navigate(`/admin/users/${profile.user_id}`)
      }
      setPendingAction(null)
    } catch {
      setError(actionType === 'deleteKey' ? t('admin.profileDetail.deleteError') : t('admin.profileDetail.actionError'))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleDownloadCurrent() {
    if (!profile) return
    setDownloadingId('current')
    try {
      saveBlob(await downloadCurrentPersistent(profile.id), `profile-${profile.id}-persistent.bin`)
    } finally {
      setDownloadingId(null)
    }
  }

  async function handleDownloadBackup(backup: Backup) {
    if (!profile) return
    setDownloadingId(backup.id)
    try {
      saveBlob(await downloadBackupPersistent(profile.id, backup.id), `profile-${profile.id}-backup-${backup.id}.bin`)
    } finally {
      setDownloadingId(null)
    }
  }

  async function handleRestoreBackup(backup: Backup) {
    if (!profile) return
    setIsBusy(true)
    setError(null)
    try {
      await restoreAdminBackup(profile.id, backup.id)
    } catch {
      setError(t('admin.profileDetail.restoreError'))
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <Box className="page-stack">
      {error ? <ErrorBanner message={error} /> : null}
      {!profile && !error ? <LoadingState /> : null}
      {profile ? (
        <>
          <Box className="page-heading">
            <Box>
              <Text as="h1">{profile.display_name || t('admin.profileDetail.profileTitle', {id: profile.id})}</Text>
              <Text as="p">
                {t('admin.profileDetail.userCreated', {id: profile.user_id})} <RelativeTime value={profile.created_at} />
              </Text>
            </Box>
            <StatusLabel status={profile.revoked_at ? 'revoked' : 'active'} />
          </Box>
          <Box className="panel">
            <Text as="h2" sx={{fontSize: 2, mt: 0}}>
              {t('admin.profileDetail.profileKey')}
            </Text>
            <CopyableSecret value={profile.profile_key} />
            <Box className="meta-line">
              {t('admin.profileDetail.lastUsed')} <RelativeTime value={profile.last_used_at} /> · {t('admin.profileDetail.lastUpload')}{' '}
              <RelativeTime value={profile.last_upload_at} />
            </Box>
            <Box className="info-grid" sx={{mt: 3}}>
              <Box className="info-cell">
                <span>{t('admin.profileDetail.profileFileSize')}</span>
                <strong>
                  <ByteSize value={profile.storage_usage} />
                </strong>
              </Box>
            </Box>
            <StorageUsageBar usage={profile.storage_usage} limit={profile.storage_limit} />
          </Box>
          <Box className="panel">
            <Box className="section-heading">
              <Box>
                <Text as="h2" sx={{fontSize: 2, mt: 0, mb: 1}}>
                  {t('admin.profileDetail.currentPersistent')}
                </Text>
                {current ? (
                  <Text as="p" sx={{color: 'fg.muted', m: 0}}>
                    {t('admin.profileDetail.versionUploaded', {id: current.id})} <RelativeTime value={current.created_at} />
                  </Text>
                ) : null}
              </Box>
              {current ? (
                <Button type="button" leadingVisual={DownloadIcon} onClick={handleDownloadCurrent} disabled={downloadingId === 'current'}>
                  {t('admin.profileDetail.downloadCurrent')}
                </Button>
              ) : null}
            </Box>
            {current ? (
              <Box className="info-grid">
                <Info label={t('admin.profileDetail.size')} value={<ByteSize value={current.size} />} />
                <Info label="SHA-256" value={<code className="truncate">{current.sha256}</code>} />
                <Info label="Ren'Py" value={current.renpy_version || t('admin.profileDetail.unknown')} />
                <Info label="MAS" value={current.mas_version || t('admin.profileDetail.unknown')} />
              </Box>
            ) : (
              <Box className="empty-inline">
                <Text as="strong">{t('admin.profileDetail.noCurrentTitle')}</Text>
                <Text as="p">{t('admin.profileDetail.noCurrentMessage')}</Text>
              </Box>
            )}
          </Box>
          <Box className="action-grid">
            <Button type="button" variant="danger" leadingVisual={BlockedIcon} onClick={() => setPendingAction('banProfile')}>
              {t('admin.profileDetail.banProfile')}
            </Button>
            <Button type="button" leadingVisual={ShieldCheckIcon} onClick={() => setPendingAction('unbanProfile')}>
              {t('admin.profileDetail.unbanProfile')}
            </Button>
            <Button type="button" variant="danger" leadingVisual={BlockedIcon} onClick={() => setPendingAction('banKey')}>
              {t('admin.profileDetail.banKey')}
            </Button>
            <Button type="button" leadingVisual={ShieldCheckIcon} onClick={() => setPendingAction('unbanKey')}>
              {t('admin.profileDetail.unbanKey')}
            </Button>
            <Button type="button" leadingVisual={SyncIcon} onClick={() => setPendingAction('refreshKey')} disabled={Boolean(profile.revoked_at)}>
              {t('admin.profileDetail.refreshKey')}
            </Button>
            <Button type="button" variant="danger" leadingVisual={TrashIcon} onClick={() => setPendingAction('deleteKey')}>
              {t('admin.profileDetail.deleteKey')}
            </Button>
            <Button type="button" leadingVisual={UnlockIcon} onClick={() => setPendingAction('releaseLock')}>
              {t('admin.profileDetail.releaseLock')}
            </Button>
          </Box>
          <Box className="table-panel">
            <Box className="table-heading">
              <Box>
                <Text as="h2" sx={{fontSize: 2, mt: 0, mb: 1}}>
                  {t('admin.profileDetail.dailyBackups')}
                </Text>
                <Text as="p" sx={{color: 'fg.muted', m: 0}}>
                  {t('admin.profileDetail.retainedBackups', {count: backups.length})}
                </Text>
              </Box>
            </Box>
            {backups.length === 0 ? (
              <EmptyState title={t('admin.profileDetail.noBackupsTitle')} message={t('admin.profileDetail.noBackupsMessage')} />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>{t('admin.profileDetail.date')}</th>
                    <th>{t('admin.profileDetail.size')}</th>
                    <th>SHA-256</th>
                    <th>{t('admin.profileDetail.createdColumn')}</th>
                    <th>{t('admin.profileDetail.actions')}</th>
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
                            aria-label={t('admin.profileDetail.downloadBackup', {date: backup.backup_date})}
                            onClick={() => handleDownloadBackup(backup)}
                            disabled={downloadingId === backup.id}
                          >
                            {t('admin.profileDetail.download')}
                          </Button>
                          <Button
                            type="button"
                            size="small"
                            variant="danger"
                            aria-label={t('admin.profileDetail.restoreBackup', {date: backup.backup_date})}
                            onClick={() => handleRestoreBackup(backup)}
                            disabled={isBusy}
                          >
                            {t('admin.profileDetail.restore')}
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
      {pendingAction ? (
        <ConfirmDialog
          title={actionTitle(pendingAction, t)}
          message={pendingAction === 'deleteKey' ? t('admin.profileDetail.deleteMessage') : t('admin.profileDetail.actionMessage')}
          confirmText={actionConfirmText(pendingAction, t)}
          variant={pendingAction.includes('ban') || pendingAction.includes('delete') ? 'danger' : 'primary'}
          onConfirm={handleConfirm}
          onCancel={() => setPendingAction(null)}
          isBusy={isBusy}
        />
      ) : null}
    </Box>
  )
}

async function getOptionalAdminCurrentPersistent(profileId: number): Promise<Version | null> {
  try {
    return await getAdminCurrentPersistent(profileId)
  } catch (error) {
    if (error instanceof ApiError && error.code === 'no_current_persistent') {
      return null
    }
    throw error
  }
}

function Info({label, value}: {label: string; value: ReactNode}) {
  return (
    <Box className="info-cell">
      <span>{label}</span>
      <strong>{value}</strong>
    </Box>
  )
}

function actionTitle(action: PendingAction, t: TFunction) {
  return action ? t(`admin.profileDetail.actionTitles.${action}`) : ''
}

function actionConfirmText(action: PendingAction, t: TFunction) {
  return action ? t(`admin.profileDetail.actionConfirm.${action}`) : ''
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
