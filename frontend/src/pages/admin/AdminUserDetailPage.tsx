import {Box, Button, Text} from '@primer/react'
import {BlockedIcon, ShieldCheckIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {useNavigate, useParams} from 'react-router-dom'
import {banUser, getAdminUser, unbanUser} from '../../api/adminApi'
import type {User} from '../../api/types'
import {AvatarName} from '../../components/AvatarName'
import {ConfirmDialog} from '../../components/ConfirmDialog'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'
import {RelativeTime} from '../../components/RelativeTime'
import {StatusLabel} from '../../components/StatusLabel'

type PendingAction = 'ban' | 'unban' | null

export function AdminUserDetailPage() {
  const {userId} = useParams()
  const numericUserId = Number(userId)
  const [user, setUser] = useState<User | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [profileId, setProfileId] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (!Number.isFinite(numericUserId)) {
      setError('Invalid user id.')
      return
    }
    getAdminUser(numericUserId)
      .then((response) => setUser(response.user))
      .catch(() => setError('Could not load this user.'))
  }, [numericUserId])

  async function handleConfirm() {
    if (!pendingAction || !user) {
      return
    }
    setIsBusy(true)
    try {
      if (pendingAction === 'ban') {
        await banUser(user.id)
      } else {
        await unbanUser(user.id)
      }
      setPendingAction(null)
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <Box className="page-stack">
      {error ? <ErrorBanner message={error} /> : null}
      {!user && !error ? <LoadingState /> : null}
      {user ? (
        <>
          <Box className="detail-header">
            <AvatarName user={user} subtitle={`Flarum #${user.flarum_user_id}`} />
            <Box sx={{display: 'flex', gap: 2}}>
              <Button type="button" variant="danger" leadingVisual={BlockedIcon} onClick={() => setPendingAction('ban')}>
                Ban user
              </Button>
              <Button type="button" leadingVisual={ShieldCheckIcon} onClick={() => setPendingAction('unban')}>
                Unban user
              </Button>
            </Box>
          </Box>
          <Box className="info-grid">
            <Info label="User ID" value={`#${user.id}`} />
            <Info label="Username" value={user.username} />
            <Info label="Display name" value={user.display_name || 'Unset'} />
            <Info label="Role" value={<StatusLabel status={user.role} />} />
            <Info label="Last login" value={<RelativeTime value={user.last_login_at} />} />
          </Box>
          <Box className="panel">
            <Text as="h2" sx={{fontSize: 2, mt: 0}}>
              Open profile by ID
            </Text>
            <form
              className="inline-form"
              onSubmit={(event) => {
                event.preventDefault()
                if (profileId.trim()) {
                  navigate(`/admin/profiles/${profileId.trim()}`)
                }
              }}
            >
              <label className="field inline-field">
                <span>Profile ID</span>
                <input value={profileId} onChange={(event) => setProfileId(event.target.value)} inputMode="numeric" />
              </label>
              <Button type="submit">Open profile</Button>
            </form>
          </Box>
        </>
      ) : null}
      {pendingAction ? (
        <ConfirmDialog
          title={pendingAction === 'ban' ? 'Ban this user?' : 'Unban this user?'}
          message={pendingAction === 'ban' ? 'All profile keys under this user will be denied.' : 'This removes active user-level bans.'}
          confirmText={pendingAction === 'ban' ? 'Ban user' : 'Unban user'}
          variant={pendingAction === 'ban' ? 'danger' : 'primary'}
          onConfirm={handleConfirm}
          onCancel={() => setPendingAction(null)}
          isBusy={isBusy}
        />
      ) : null}
    </Box>
  )
}

function Info({label, value}: {label: string; value: React.ReactNode}) {
  return (
    <Box className="info-cell">
      <Text as="span">{label}</Text>
      <Text as="strong">{value}</Text>
    </Box>
  )
}
