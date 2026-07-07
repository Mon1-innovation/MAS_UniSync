import {Box, Button, Text} from '@primer/react'
import {BlockedIcon, DownloadIcon, ShieldCheckIcon, SyncIcon, TrashIcon, UnlockIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {useNavigate, useParams} from 'react-router-dom'
import {
  banProfile,
  banProfileKey,
  deleteAdminProfileKey,
  downloadBackupPersistent,
  downloadCurrentPersistent,
  getAdminProfile,
  refreshAdminProfileKey,
  releaseAdminLock,
  restoreAdminBackup,
  unbanProfile,
  unbanProfileKey,
} from '../../api/adminApi'
import type {Profile} from '../../api/types'
import {ConfirmDialog} from '../../components/ConfirmDialog'
import {CopyableSecret} from '../../components/CopyableSecret'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'
import {RelativeTime} from '../../components/RelativeTime'
import {StatusLabel} from '../../components/StatusLabel'

type PendingAction = 'banProfile' | 'unbanProfile' | 'banKey' | 'unbanKey' | 'refreshKey' | 'deleteKey' | 'releaseLock' | null

export function AdminProfileDetailPage() {
  const {profileId} = useParams()
  const navigate = useNavigate()
  const numericProfileId = Number(profileId)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [backupId, setBackupId] = useState('')
  const [isBusy, setIsBusy] = useState(false)

  useEffect(() => {
    if (!Number.isFinite(numericProfileId)) {
      setError('Invalid profile id.')
      return
    }
    getAdminProfile(numericProfileId)
      .then((response) => setProfile(response.profile))
      .catch(() => setError('Could not load this profile.'))
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
    saveBlob(await downloadCurrentPersistent(profile.id), `profile-${profile.id}-persistent.bin`)
  }

  async function handleDownloadBackup(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!profile || !backupId.trim()) return
    saveBlob(await downloadBackupPersistent(profile.id, Number(backupId)), `profile-${profile.id}-backup-${backupId}.bin`)
  }

  async function handleRestoreBackup(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!profile || !backupId.trim()) return
    await restoreAdminBackup(profile.id, Number(backupId))
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
            <Button type="button" leadingVisual={DownloadIcon} onClick={handleDownloadCurrent}>
              Download current
            </Button>
          </Box>
          <Box className="panel">
            <Text as="h2" sx={{fontSize: 2, mt: 0}}>
              Backup by ID
            </Text>
            <Text as="p" sx={{color: 'fg.muted'}}>
              Admin backup browsing needs GET /admin/profiles/:profileId/persistent/backups. Until then, download or restore a known backup ID.
            </Text>
            <Box className="backup-tools">
              <form className="inline-form" onSubmit={handleDownloadBackup}>
                <label className="field inline-field">
                  <span>Backup ID</span>
                  <input value={backupId} onChange={(event) => setBackupId(event.target.value)} inputMode="numeric" />
                </label>
                <Button type="submit" leadingVisual={DownloadIcon}>
                  Download backup
                </Button>
              </form>
              <form className="inline-form" onSubmit={handleRestoreBackup}>
                <Button type="submit" variant="danger" disabled={!backupId.trim()}>
                  Restore backup
                </Button>
              </form>
            </Box>
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
