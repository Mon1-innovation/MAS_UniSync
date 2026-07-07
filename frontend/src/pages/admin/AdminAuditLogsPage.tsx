import {Box, Text} from '@primer/react'
import {useEffect, useMemo, useState} from 'react'
import {Link} from 'react-router-dom'
import {listAuditLogs} from '../../api/adminApi'
import type {AuditLog} from '../../api/types'
import {EmptyState} from '../../components/EmptyState'
import {ErrorBanner} from '../../components/ErrorBanner'
import {LoadingState} from '../../components/LoadingState'
import {RelativeTime} from '../../components/RelativeTime'
import {StatusLabel} from '../../components/StatusLabel'

export function AdminAuditLogsPage() {
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
          setError('Could not load audit logs.')
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
  }, [])

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
          <Text as="h1">Audit logs</Text>
          <Text as="p">Recent administrative and profile-key activity.</Text>
        </Box>
        <input className="search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter action or target" />
      </Box>
      {error ? <ErrorBanner message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && filteredLogs.length === 0 ? <EmptyState title="No audit logs" message="No log entries match the current filter." /> : null}
      {filteredLogs.length > 0 ? (
        <Box className="table-panel">
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Actor</th>
                <th>Targets</th>
                <th>IP</th>
                <th>User agent</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.map((log) => (
                <tr key={log.id}>
                  <td>
                    <Text sx={{fontFamily: 'mono'}}>{log.action}</Text>
                  </td>
                  <td>
                    #{log.actor_user_id || 'system'} <StatusLabel status={log.actor_role} />
                  </td>
                  <td>
                    <TargetLinks log={log} />
                  </td>
                  <td>{log.ip_address || 'Unknown'}</td>
                  <td className="truncate">{log.user_agent || 'Unknown'}</td>
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
  return (
    <Box sx={{display: 'flex', gap: 2, flexWrap: 'wrap'}}>
      {log.target_user_id ? <span>User #{log.target_user_id}</span> : null}
      {log.target_profile_id ? <Link to={`/admin/profiles/${log.target_profile_id}`}>#{log.target_profile_id}</Link> : null}
      {log.target_profile_key_id ? <span>Key #{log.target_profile_key_id}</span> : null}
      {!log.target_user_id && !log.target_profile_id && !log.target_profile_key_id ? <span className="muted">None</span> : null}
    </Box>
  )
}
