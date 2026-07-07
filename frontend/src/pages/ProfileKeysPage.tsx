import {Box, Button, Text} from '@primer/react'
import {FileDirectoryIcon, KeyIcon, PlusIcon, SyncIcon, TrashIcon} from '@primer/octicons-react'
import {useEffect, useMemo, useState} from 'react'
import {Link} from 'react-router-dom'
import {createProfileKey, deleteProfileKey, listProfileKeys, refreshProfileKey} from '../api/profileKeysApi'
import type {Profile} from '../api/types'
import {ConfirmDialog} from '../components/ConfirmDialog'
import {CopyableSecret} from '../components/CopyableSecret'
import {EmptyState} from '../components/EmptyState'
import {ErrorBanner} from '../components/ErrorBanner'
import {FormDialog} from '../components/FormDialog'
import {LoadingState} from '../components/LoadingState'
import {RelativeTime} from '../components/RelativeTime'
import {StatusLabel} from '../components/StatusLabel'

type PendingAction = {type: 'refresh' | 'delete'; profile: Profile} | null

export function ProfileKeysPage() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [isBusy, setIsBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    listProfileKeys()
      .then((response) => {
        if (!cancelled) {
          setProfiles(response.items)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Could not load profile keys.')
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

  const sortedProfiles = useMemo(() => [...profiles].sort((a, b) => a.id - b.id), [profiles])

  function replaceProfile(nextProfile: Profile) {
    setProfiles((current) => current.map((profile) => (profile.id === nextProfile.id ? nextProfile : profile)))
  }

  function removeProfile(profileId: number) {
    setProfiles((current) => current.filter((profile) => profile.id !== profileId))
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsBusy(true)
    try {
      const profile = await createProfileKey(createName.trim() || null)
      setProfiles((current) => [...current, profile])
      setCreateName('')
      setIsCreateOpen(false)
    } finally {
      setIsBusy(false)
    }
  }

  async function handleConfirmAction() {
    if (!pendingAction) {
      return
    }
    setIsBusy(true)
    try {
      if (pendingAction.type === 'refresh') {
        replaceProfile(await refreshProfileKey(pendingAction.profile.id))
      } else {
        await deleteProfileKey(pendingAction.profile.id)
        removeProfile(pendingAction.profile.id)
      }
      setPendingAction(null)
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <Box className="page-stack">
      <Box className="page-heading">
        <Box>
          <Text as="h1">Profile keys</Text>
          <Text as="p">Manage the keys your MAS submod uses to sync persistent data.</Text>
        </Box>
        <Button type="button" variant="primary" leadingVisual={PlusIcon} onClick={() => setIsCreateOpen(true)}>
          New profile key
        </Button>
      </Box>

      {error ? <ErrorBanner message={error} /> : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && sortedProfiles.length === 0 ? <EmptyState title="No profile keys" message="Create a key before configuring the submod." /> : null}

      <Box className="panel-list">
        {sortedProfiles.map((profile) => (
          <Box key={profile.id} className={`profile-row ${profile.revoked_at ? 'is-muted' : ''}`}>
            <Box className="row-icon">
              <KeyIcon size={20} />
            </Box>
            <Box className="row-main">
              <Box sx={{display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap'}}>
                <Text as="h2" sx={{fontSize: 2, m: 0}}>
                  {profile.display_name || `Profile #${profile.id}`}
                </Text>
                <StatusLabel status={profile.revoked_at ? 'revoked' : 'active'} />
              </Box>
              <Text as="p" sx={{color: 'fg.muted', my: 1}}>
                Profile ID #{profile.id} · Created <RelativeTime value={profile.created_at} /> · Last used{' '}
                <RelativeTime value={profile.last_used_at} /> · Last upload <RelativeTime value={profile.last_upload_at} />
              </Text>
              <CopyableSecret value={profile.profile_key} />
            </Box>
            <Box className="row-actions">
              <Button as={Link} to={`/account/profiles/${profile.id}`} size="small" leadingVisual={FileDirectoryIcon}>
                View files
              </Button>
              <Button
                type="button"
                size="small"
                leadingVisual={SyncIcon}
                aria-label={`Refresh key for ${profile.display_name || profile.id}`}
                onClick={() => setPendingAction({type: 'refresh', profile})}
                disabled={Boolean(profile.revoked_at)}
              >
                Refresh key
              </Button>
              <Button
                type="button"
                size="small"
                variant="danger"
                leadingVisual={TrashIcon}
                aria-label={`Delete key for ${profile.display_name || profile.id}`}
                onClick={() => setPendingAction({type: 'delete', profile})}
                disabled={Boolean(profile.revoked_at)}
              >
                Delete key
              </Button>
            </Box>
          </Box>
        ))}
      </Box>

      {isCreateOpen ? (
        <form onSubmit={handleCreate}>
          <FormDialog title="New profile key" submitText="Create key" onCancel={() => setIsCreateOpen(false)} isBusy={isBusy}>
            <label className="field">
              <span>Display name</span>
              <input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="Main persistent" autoFocus />
            </label>
          </FormDialog>
        </form>
      ) : null}

      {pendingAction ? (
        <ConfirmDialog
          title={pendingAction.type === 'refresh' ? 'Refresh profile key?' : 'Delete profile key?'}
          message={
            pendingAction.type === 'refresh'
              ? 'The old key will stop working immediately. Copy the new key after refreshing.'
              : 'This profile key and its stored persistent files will be deleted.'
          }
          confirmText={pendingAction.type === 'refresh' ? 'Refresh' : 'Delete'}
          onConfirm={handleConfirmAction}
          onCancel={() => setPendingAction(null)}
          isBusy={isBusy}
        />
      ) : null}
    </Box>
  )
}
