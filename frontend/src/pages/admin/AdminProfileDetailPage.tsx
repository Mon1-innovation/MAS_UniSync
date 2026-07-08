import {Box, Button, Text} from '@primer/react'
import {BlockedIcon, DownloadIcon, ShieldCheckIcon, SyncIcon, TrashIcon, UnlockIcon, VersionsIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import type {ReactNode} from 'react'
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
      setError('Invalid profile id.')
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
          setError('Could not load this profile.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [numericProfileId])

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
      setError(actionType === 'deleteKey' ? 'Could not delete this profile key.' : 'Could not complete this admin action.')
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
      setError('Could not restore this backup.')
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
              <Text as="h1">{profile.display_name || `Profile #${profile.id}`}</Text>
              <Text as="p">User #{profile.user_id} · Created <RelativeTime value={profile.created_at} /></Text>
            </Box>
            <StatusLabel status={profile.revoked_at ? 'revoked' : 'active'} />
          </Box>
          <Box className="panel">
            <Text as="h2" sx={{fontSize: 2, mt: 0}}>
              Profile key
            </Text>
            <CopyableSecret value={profile.profile_key} />
            <Box className="meta-line">
              Last used <RelativeTime value={profile.last_used_at} /> · Last upload <RelativeTime value={profile.last_upload_at} />
            </Box>
            <Box className="info-grid" sx={{mt: 3}}>
              <Box className="info-cell">
                <span>Profile file size</span>
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
                  Current persistent
                </Text>
                {current ? (
                  <Text as="p" sx={{color: 'fg.muted', m: 0}}>
                    Version #{current.id} · Uploaded <RelativeTime value={current.created_at} />
                  </Text>
                ) : null}
              </Box>
              {current ? (
                <Button type="button" leadingVisual={DownloadIcon} onClick={handleDownloadCurrent} disabled={downloadingId === 'current'}>
                  Download current
                </Button>
              ) : null}
            </Box>
            {current ? (
              <Box className="info-grid">
                <Info label="Size" value={<ByteSize value={current.size} />} />
                <Info label="SHA-256" value={<code className="truncate">{current.sha256}</code>} />
                <Info label="Ren'Py" value={current.renpy_version || 'Unknown'} />
                <Info label="MAS" value={current.mas_version || 'Unknown'} />
              </Box>
            ) : (
              <Box className="empty-inline">
                <Text as="strong">No current persistent</Text>
                <Text as="p">This profile does not have an uploaded persistent file yet.</Text>
              </Box>
            )}
          </Box>
          <Box className="action-grid">
            <Button type="button" variant="danger" leadingVisual={BlockedIcon} onClick={() => setPendingAction('banProfile')}>
              Ban profile
            </Button>
            <Button type="button" leadingVisual={ShieldCheckIcon} onClick={() => setPendingAction('unbanProfile')}>
              Unban profile
            </Button>
            <Button type="button" variant="danger" leadingVisual={BlockedIcon} onClick={() => setPendingAction('banKey')}>
              Ban key
            </Button>
            <Button type="button" leadingVisual={ShieldCheckIcon} onClick={() => setPendingAction('unbanKey')}>
              Unban key
            </Button>
            <Button type="button" leadingVisual={SyncIcon} onClick={() => setPendingAction('refreshKey')} disabled={Boolean(profile.revoked_at)}>
              Refresh key
            </Button>
            <Button type="button" variant="danger" leadingVisual={TrashIcon} onClick={() => setPendingAction('deleteKey')}>
              Delete key
            </Button>
            <Button type="button" leadingVisual={UnlockIcon} onClick={() => setPendingAction('releaseLock')}>
              Force-release lock
            </Button>
          </Box>
          <Box className="table-panel">
            <Box className="table-heading">
              <Box>
                <Text as="h2" sx={{fontSize: 2, mt: 0, mb: 1}}>
                  Daily backups
                </Text>
                <Text as="p" sx={{color: 'fg.muted', m: 0}}>
                  {backups.length} retained backup{backups.length === 1 ? '' : 's'}
                </Text>
              </Box>
            </Box>
            {backups.length === 0 ? (
              <EmptyState title="No backups" message="Backups appear after successful daily uploads." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Size</th>
                    <th>SHA-256</th>
                    <th>Created</th>
                    <th>Actions</th>
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
                            aria-label={`Download backup ${backup.backup_date}`}
                            onClick={() => handleDownloadBackup(backup)}
                            disabled={downloadingId === backup.id}
                          >
                            Download
                          </Button>
                          <Button
                            type="button"
                            size="small"
                            variant="danger"
                            aria-label={`Restore backup ${backup.backup_date}`}
                            onClick={() => handleRestoreBackup(backup)}
                            disabled={isBusy}
                          >
                            Restore
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
          title={actionTitle(pendingAction)}
          message={
            pendingAction === 'deleteKey'
              ? 'This profile key and its stored persistent files will be deleted. The admin action will be recorded in audit logs.'
              : 'This admin action is applied immediately and will be recorded in audit logs.'
          }
          confirmText={actionConfirmText(pendingAction)}
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

function actionTitle(action: PendingAction) {
  const labels: Record<Exclude<PendingAction, null>, string> = {
    banProfile: 'Ban this profile?',
    unbanProfile: 'Unban this profile?',
    banKey: 'Ban this key?',
    unbanKey: 'Unban this key?',
    refreshKey: 'Refresh this key?',
    deleteKey: 'Delete this key?',
    releaseLock: 'Force-release lock?',
  }
  return action ? labels[action] : ''
}

function actionConfirmText(action: PendingAction) {
  return actionTitle(action).replace('?', '')
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
