import {Box, Button, Text} from '@primer/react'
import {SearchIcon} from '@primer/octicons-react'
import {useEffect, useMemo, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {useNavigate} from 'react-router-dom'
import {ApiError} from '../../api/client'
import {listAdminUsers} from '../../api/adminApi'
import type {AdminUserListItem} from '../../api/types'
import {useAuth} from '../../auth/AuthProvider'
import {AvatarName} from '../../components/AvatarName'
import {ByteSize} from '../../components/ByteSize'
import {EmptyState} from '../../components/EmptyState'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'
import {RelativeTime} from '../../components/RelativeTime'
import {StatusLabel} from '../../components/StatusLabel'

export function AdminUsersPage() {
  const {t} = useTranslation()
  const [users, setUsers] = useState<AdminUserListItem[]>([])
  const [query, setQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const {user, setUser} = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    listAdminUsers()
      .then((response) => {
        if (!cancelled) {
          setUsers(response.items)
        }
      })
      .catch((caught) => {
        if (cancelled) {
          return
        }
        if (caught instanceof ApiError && caught.status === 403) {
          if (user) {
            setUser({...user, role: 'user'})
          }
          setError(t('admin.users.accessDeniedMessage'))
        } else {
          setError(t('admin.users.loadError'))
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
  }, [setUser, t, user])

  const filteredUsers = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) {
      return users
    }
    return users.filter((item) =>
      [
        item.username,
        item.display_name || '',
        String(item.flarum_user_id),
        item.role,
        item.lock_status,
        item.ban_status,
      ]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    )
  }, [query, users])

  return (
    <Box className="page-stack">
      <Box className="page-heading">
        <Box>
          <Text as="h1">{t('admin.users.title')}</Text>
          <Text as="p">{t('admin.users.description')}</Text>
        </Box>
        <Box className="search-box">
          <SearchIcon size={16} aria-hidden="true" />
          <input
            className="search-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('admin.users.searchPlaceholder')}
          />
        </Box>
      </Box>
      {error ? <ErrorBanner title={t('admin.accessDeniedTitle')} message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && filteredUsers.length === 0 ? (
        <EmptyState title={t('admin.users.emptyTitle')} message={t('admin.users.emptyMessage')} />
      ) : null}
      {filteredUsers.length > 0 ? (
        <Box className="table-panel">
          <table>
            <thead>
              <tr>
                <th>{t('admin.users.user')}</th>
                <th>{t('admin.users.role')}</th>
                <th>{t('admin.users.profiles')}</th>
                <th>{t('admin.users.storage')}</th>
                <th>{t('admin.users.lastLogin')}</th>
                <th>{t('admin.users.lastSubmodUse')}</th>
                <th>{t('admin.users.lastUpload')}</th>
                <th>{t('admin.users.lock')}</th>
                <th>{t('admin.users.ban')}</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((item) => (
                <tr key={item.id} className="clickable-row" onClick={() => navigate(`/admin/users/${item.id}`)}>
                  <td>
                    <AvatarName user={item} subtitle={`Flarum #${item.flarum_user_id}`} />
                  </td>
                  <td>
                    <StatusLabel status={item.role} />
                  </td>
                  <td>{item.profile_count}</td>
                  <td>
                    <ByteSize value={item.storage_usage} />
                  </td>
                  <td>
                    <RelativeTime value={item.last_login_at} />
                  </td>
                  <td>
                    <RelativeTime value={item.last_submod_use} />
                  </td>
                  <td>
                    <RelativeTime value={item.last_upload_at} />
                  </td>
                  <td>
                    <StatusLabel status={item.lock_status} />
                  </td>
                  <td>
                    <StatusLabel status={item.ban_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Box>
      ) : null}
      <Box className="compact-tools">
        <OpenProfileById />
      </Box>
    </Box>
  )
}

function OpenProfileById() {
  const {t} = useTranslation()
  const [profileId, setProfileId] = useState('')
  const navigate = useNavigate()
  return (
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
        <span>{t('admin.users.openProfileById')}</span>
        <input value={profileId} onChange={(event) => setProfileId(event.target.value)} inputMode="numeric" />
      </label>
      <Button type="submit">{t('admin.users.open')}</Button>
    </form>
  )
}
