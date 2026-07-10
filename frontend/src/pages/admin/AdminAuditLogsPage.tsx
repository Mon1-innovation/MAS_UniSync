import {Box, Button, Text} from '@primer/react'
import {SearchIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link} from 'react-router-dom'
import {listAuditLogs} from '../../api/adminApi'
import type {AuditLog} from '../../api/types'
import {EmptyState} from '../../components/EmptyState'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'
import {RelativeTime} from '../../components/RelativeTime'
import {StatusLabel} from '../../components/StatusLabel'

export function AdminAuditLogsPage() {
  const {t} = useTranslation()
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<25 | 50 | 100>(25)
  const [hasNext, setHasNext] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    setError(null)
    listAuditLogs({page, page_size: pageSize, q: query.trim() || undefined})
      .then((response) => {
        if (!cancelled) {
          setLogs(response.items)
          setHasNext(Boolean(response.has_next))
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(t('admin.auditLogs.loadError'))
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
  }, [page, pageSize, query, t])

  return (
    <Box className="page-stack">
      <Box className="page-heading">
        <Box>
          <Text as="h1">{t('admin.auditLogs.title')}</Text>
          <Text as="p">{t('admin.auditLogs.description')}</Text>
        </Box>
        <Box className="search-box">
          <SearchIcon size={16} aria-hidden="true" />
          <input
            className="search-input"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setPage(1)
            }}
            placeholder={t('admin.auditLogs.filterPlaceholder')}
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
              setPage(1)
            }}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
      </Box>
      {error ? <ErrorBanner message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && logs.length === 0 ? (
        <EmptyState title={t('admin.auditLogs.emptyTitle')} message={t('admin.auditLogs.emptyMessage')} />
      ) : null}
      {logs.length > 0 ? (
        <Box className="table-panel">
          <table>
            <thead>
              <tr>
                <th>{t('admin.auditLogs.action')}</th>
                <th>{t('admin.auditLogs.actor')}</th>
                <th>{t('admin.auditLogs.targets')}</th>
                <th>{t('admin.auditLogs.ip')}</th>
                <th>{t('admin.auditLogs.userAgent')}</th>
                <th>{t('admin.auditLogs.created')}</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td>
                    <Text sx={{fontFamily: 'mono'}}>{log.action}</Text>
                  </td>
                  <td>
                    {log.actor_user_id ? `#${log.actor_user_id}` : t('admin.auditLogs.system')} <StatusLabel status={log.actor_role} />
                  </td>
                  <td>
                    <TargetLinks log={log} />
                  </td>
                  <td>{log.ip_address || t('admin.auditLogs.unknown')}</td>
                  <td className="truncate">{log.user_agent || t('admin.auditLogs.unknown')}</td>
                  <td>
                    <RelativeTime value={log.created_at} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Box>
      ) : null}
      <PaginationControls page={page} hasNext={hasNext} onPrevious={() => setPage((value) => Math.max(1, value - 1))} onNext={() => setPage((value) => value + 1)} />
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

function TargetLinks({log}: {log: AuditLog}) {
  const {t} = useTranslation()
  return (
    <Box sx={{display: 'flex', gap: 2, flexWrap: 'wrap'}}>
      {log.target_user_id ? <span>{t('admin.auditLogs.userTarget', {id: log.target_user_id})}</span> : null}
      {log.target_profile_id ? <Link to={`/admin/profiles/${log.target_profile_id}`}>#{log.target_profile_id}</Link> : null}
      {log.target_profile_key_id ? <span>{t('admin.auditLogs.keyTarget', {id: log.target_profile_key_id})}</span> : null}
      {!log.target_user_id && !log.target_profile_id && !log.target_profile_key_id ? (
        <span className="muted">{t('admin.auditLogs.none')}</span>
      ) : null}
    </Box>
  )
}
