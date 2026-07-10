import {Box, Button, Text} from '@primer/react'
import {SearchIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {useNavigate} from 'react-router-dom'
import {ApiError} from '../../api/client'
import {listAdminUsers} from '../../api/adminApi'
import type {AdminUserListItem, AdminUserSort, SortOrder} from '../../api/types'
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
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<25 | 50 | 100>(25)
  const [sort, setSort] = useState<AdminUserSort>('id')
  const [order, setOrder] = useState<SortOrder>('asc')
  const [lastUploadFrom, setLastUploadFrom] = useState('')
  const [lastUploadTo, setLastUploadTo] = useState('')
  const [hasNext, setHasNext] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const {user, setUser} = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    setError(null)
    listAdminUsers({
      page,
      page_size: pageSize,
      q: query.trim() || undefined,
      sort,
      order,
      last_upload_from: lastUploadFrom || undefined,
      last_upload_to: lastUploadTo || undefined,
    })
      .then((response) => {
        if (!cancelled) {
          setUsers(response.items)
          setHasNext(Boolean(response.has_next))
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
  }, [lastUploadFrom, lastUploadTo, order, page, pageSize, query, setUser, sort, t, user])

  const resetPage = () => setPage(1)

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
            onChange={(event) => {
              setQuery(event.target.value)
              resetPage()
            }}
            placeholder={t('admin.users.searchPlaceholder')}
          />
        </Box>
      </Box>
      <Box className="compact-tools">
        <label className="field inline-field">
          <span>{t('admin.pagination.pageSize')}</span>
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value) as 25 | 50 | 100)
              resetPage()
            }}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
        <label className="field inline-field">
          <span>{t('admin.users.sortField')}</span>
          <select
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as AdminUserSort)
              resetPage()
            }}
          >
            <option value="id">{t('admin.users.sortId')}</option>
            <option value="last_upload_at">{t('admin.users.sortLastUpload')}</option>
          </select>
        </label>
        <label className="field inline-field">
          <span>{t('admin.users.sortOrder')}</span>
          <select
            value={order}
            onChange={(event) => {
              setOrder(event.target.value as SortOrder)
              resetPage()
            }}
          >
            <option value="asc">{t('admin.users.sortAsc')}</option>
            <option value="desc">{t('admin.users.sortDesc')}</option>
          </select>
        </label>
        <label className="field inline-field">
          <span>{t('admin.users.lastUploadFrom')}</span>
          <input
            type="date"
            value={lastUploadFrom}
            onChange={(event) => {
              setLastUploadFrom(event.target.value)
              resetPage()
            }}
          />
        </label>
        <label className="field inline-field">
          <span>{t('admin.users.lastUploadTo')}</span>
          <input
            type="date"
            value={lastUploadTo}
            onChange={(event) => {
              setLastUploadTo(event.target.value)
              resetPage()
            }}
          />
        </label>
      </Box>
      {error ? <ErrorBanner title={t('admin.accessDeniedTitle')} message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && users.length === 0 ? (
        <EmptyState title={t('admin.users.emptyTitle')} message={t('admin.users.emptyMessage')} />
      ) : null}
      {users.length > 0 ? (
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
              {users.map((item) => (
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
      <PaginationControls page={page} hasNext={hasNext} onPrevious={() => setPage((value) => Math.max(1, value - 1))} onNext={() => setPage((value) => value + 1)} />
      <Box className="compact-tools">
        <OpenProfileById />
      </Box>
    </Box>
  )
}

function PaginationControls({
  page,
  hasNext,
  onPrevious,
  onNext,
}: {
  page: number
  hasNext: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  const {t} = useTranslation()
  return (
    <Box className="compact-tools" aria-label={t('admin.pagination.label')}>
      <Button type="button" onClick={onPrevious} disabled={page === 1}>
        {t('admin.pagination.previous')}
      </Button>
      <Text>{t('admin.pagination.page', {page})}</Text>
      <Button type="button" onClick={onNext} disabled={!hasNext}>
        {t('admin.pagination.next')}
      </Button>
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
