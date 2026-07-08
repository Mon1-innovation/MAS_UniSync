import {Box, Text} from '@primer/react'
import {SearchIcon} from '@primer/octicons-react'
import {useEffect, useMemo, useState} from 'react'
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
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listAuditLogs()
      .then((response) => {
        if (!cancelled) {
          setLogs(response.items)
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
  }, [t])

  const filteredLogs = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return logs
    return logs.filter((log) =>
      [log.action, log.target_user_id, log.target_profile_id, log.target_profile_key_id, log.actor_user_id]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    )
  }, [logs, query])

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
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('admin.auditLogs.filterPlaceholder')}
          />
        </Box>
      </Box>
      {error ? <ErrorBanner message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && filteredLogs.length === 0 ? (
        <EmptyState title={t('admin.auditLogs.emptyTitle')} message={t('admin.auditLogs.emptyMessage')} />
      ) : null}
      {filteredLogs.length > 0 ? (
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
              {filteredLogs.map((log) => (
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
