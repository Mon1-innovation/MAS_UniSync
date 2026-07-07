import {Box, Button, Text} from '@primer/react'
import {ArrowLeftIcon, DownloadIcon, VersionsIcon} from '@primer/octicons-react'
import {useEffect, useState} from 'react'
import type {ReactNode} from 'react'
import {Link, useParams} from 'react-router-dom'
import {ApiError} from '../api/client'
import {
  downloadAccountBackupPersistent,
  downloadAccountCurrentPersistent,
  getAccountCurrentPersistent,
  getAccountProfile,
  listAccountBackups,
} from '../api/profileKeysApi'
import type {Backup, Profile, Version} from '../api/types'
import {ByteSize} from '../components/ByteSize'
import {CopyableSecret} from '../components/CopyableSecret'
import {EmptyState} from '../components/EmptyState'
import {ErrorBanner} from '../components/ErrorBanner'
import {LoadingState} from '../components/LoadingState'
import {RelativeTime} from '../components/RelativeTime'
import {StatusLabel} from '../components/StatusLabel'

export function ProfileDetailPage() {
  const {profileId} = useParams()
  const numericProfileId = Number(profileId)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [current, setCurrent] = useState<Version | null>(null)
  const [backups, setBackups] = useState<Backup[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [downloadingId, setDownloadingId] = useState<number | 'current' | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!Number.isFinite(numericProfileId)) {
      setError('Invalid profile id.')
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    Promise.all([
      getAccountProfile(numericProfileId),
      getOptionalCurrentPersistent(numericProfileId),
      listAccountBackups(numericProfileId),
    ])
      .then(([profileResponse, currentVersion, backupResponse]) => {
        if (!cancelled) {
          setProfile(profileResponse.profile)
          setCurrent(currentVersion)
          setBackups(backupResponse.items)
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setError(profileLoadErrorMessage(error))
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
  }, [numericProfileId])

  async function handleDownloadCurrent() {
    if (!profile) return
    setDownloadingId('current')
    try {
      saveBlob(await downloadAccountCurrentPersistent(profile.id), `profile-${profile.id}-persistent.bin`)
    } finally {
      setDownloadingId(null)
    }
  }

  async function handleDownloadBackup(backup: Backup) {
    if (!profile) return
    setDownloadingId(backup.id)
    try {
      saveBlob(await downloadAccountBackupPersistent(profile.id, backup.id), `profile-${profile.id}-backup-${backup.id}.bin`)
    } finally {
      setDownloadingId(null)
    }
  }

  return (
    <Box className="page-stack">
      {error ? <ErrorBanner message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && profile ? (
        <>
          <Box className="page-heading">
            <Box>
              <Button as={Link} to="/account/profile-keys" leadingVisual={ArrowLeftIcon} size="small">
                Profile keys
              </Button>
              <Text as="h1" sx={{mt: 3}}>
                {profile.display_name || `Profile #${profile.id}`}
              </Text>
              <Text as="p">
                Profile ID #{profile.id} · Created <RelativeTime value={profile.created_at} /> · Last upload{' '}
                <RelativeTime value={profile.last_upload_at} />
              </Text>
            </Box>
            <StatusLabel status={profile.revoked_at ? 'revoked' : 'active'} />
          </Box>

          <Box className="panel">
            <Text as="h2" sx={{fontSize: 2, mt: 0}}>
              Profile key
            </Text>
            <CopyableSecret value={profile.profile_key} />
            <Box className="meta-line">
              Last used <RelativeTime value={profile.last_used_at} />
            </Box>
            <Box className="info-grid" sx={{mt: 3}}>
              <Info label="Profile file size" value={<ByteSize value={profile.storage_usage} />} />
            </Box>
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
                    <th>Action</th>
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
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Box>
        </>
      ) : null}
    </Box>
  )
}

async function getOptionalCurrentPersistent(profileId: number): Promise<Version | null> {
  try {
    return await getAccountCurrentPersistent(profileId)
  } catch (error) {
    if (error instanceof ApiError && error.code === 'no_current_persistent') {
      return null
    }
    throw error
  }
}

function profileLoadErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'profile_not_found') {
      return 'This profile was not found for your account.'
    }
    if (error.code === 'not_authenticated') {
      return 'Please sign in again before opening this profile.'
    }
  }
  return 'Could not load this profile.'
}

function Info({label, value}: {label: string; value: ReactNode}) {
  return (
    <Box className="info-cell">
      <span>{label}</span>
      <strong>{value}</strong>
    </Box>
  )
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
