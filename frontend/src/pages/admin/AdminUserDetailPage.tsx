import {Box, Button, Text} from '@primer/react'
import {BlockedIcon, ShieldCheckIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, useNavigate, useParams} from 'react-router-dom'
import {banUser, getAdminUser, unbanUser} from '../../api/adminApi'
import type {Profile, User} from '../../api/types'
import {AvatarName} from '../../components/AvatarName'
import {ConfirmDialog} from '../../components/ConfirmDialog'
import {EmptyState} from '../../components/EmptyState'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'
import {RelativeTime} from '../../components/RelativeTime'
import {StatusLabel} from '../../components/StatusLabel'

type PendingAction = 'ban' | 'unban' | null

export function AdminUserDetailPage() {
  const {t} = useTranslation()
  const {userId} = useParams()
  const numericUserId = Number(userId)
  const [user, setUser] = useState<User | null>(null)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [profileId, setProfileId] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (!Number.isFinite(numericUserId)) {
      setError(t('admin.userDetail.invalidUserId'))
      return
    }
    getAdminUser(numericUserId)
      .then((response) => {
        setUser(response.user)
        setProfiles(response.profiles ?? [])
      })
      .catch(() => setError(t('admin.userDetail.loadError')))
  }, [numericUserId, t])

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
                {t('admin.userDetail.banUser')}
              </Button>
              <Button type="button" leadingVisual={ShieldCheckIcon} onClick={() => setPendingAction('unban')}>
                {t('admin.userDetail.unbanUser')}
              </Button>
            </Box>
          </Box>
          <Box className="info-grid">
            <Info label={t('admin.userDetail.userId')} value={`#${user.id}`} />
            <Info label={t('admin.userDetail.username')} value={user.username} />
            <Info label={t('admin.userDetail.displayName')} value={user.display_name || t('admin.userDetail.unset')} />
            <Info label={t('admin.userDetail.role')} value={<StatusLabel status={user.role} />} />
            <Info label={t('admin.userDetail.lastLogin')} value={<RelativeTime value={user.last_login_at} />} />
          </Box>
          <Box className="table-panel">
            {profiles.length === 0 ? (
              <EmptyState title={t('admin.userDetail.noProfilesTitle')} message={t('admin.userDetail.noProfilesMessage')} />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>{t('admin.userDetail.profile')}</th>
                    <th>{t('admin.userDetail.status')}</th>
                    <th>{t('admin.userDetail.created')}</th>
                    <th>{t('admin.userDetail.lastUsed')}</th>
                    <th>{t('admin.userDetail.lastUpload')}</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((profile) => (
                    <tr key={profile.id} className="clickable-row" onClick={() => navigate(`/admin/profiles/${profile.id}`)}>
                      <td>
                        <Link to={`/admin/profiles/${profile.id}`} onClick={(event) => event.stopPropagation()}>
                          {profile.display_name || t('admin.userDetail.profileTitle', {id: profile.id})}
                        </Link>
                        <Text as="div" sx={{color: 'fg.muted', fontSize: 0}}>
                          #{profile.id}
                        </Text>
                      </td>
                      <td>
                        <StatusLabel status={profile.revoked_at ? 'revoked' : 'active'} />
                      </td>
                      <td>
                        <RelativeTime value={profile.created_at} />
                      </td>
                      <td>
                        <RelativeTime value={profile.last_used_at} />
                      </td>
                      <td>
                        <RelativeTime value={profile.last_upload_at} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Box>
          <Box className="panel">
            <Text as="h2" sx={{fontSize: 2, mt: 0}}>
              {t('admin.userDetail.openProfileById')}
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
                <span>{t('admin.userDetail.profileId')}</span>
                <input value={profileId} onChange={(event) => setProfileId(event.target.value)} inputMode="numeric" />
              </label>
              <Button type="submit">{t('admin.userDetail.openProfile')}</Button>
            </form>
          </Box>
        </>
      ) : null}
      {pendingAction ? (
        <ConfirmDialog
          title={pendingAction === 'ban' ? t('admin.userDetail.banTitle') : t('admin.userDetail.unbanTitle')}
          message={pendingAction === 'ban' ? t('admin.userDetail.banMessage') : t('admin.userDetail.unbanMessage')}
          confirmText={pendingAction === 'ban' ? t('admin.userDetail.banUser') : t('admin.userDetail.unbanUser')}
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
