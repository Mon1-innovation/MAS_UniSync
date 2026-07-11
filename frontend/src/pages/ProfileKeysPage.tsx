import {Box, Button, Text} from '@primer/react'
import {FileDirectoryIcon, KeyIcon, PencilIcon, PlusIcon, QuestionIcon, SyncIcon, TrashIcon} from '@primer/octicons-react'
import {useEffect, useMemo, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {useNavigate} from 'react-router-dom'
import {ApiError} from '../api/client'
import {createProfileKey, deleteProfileKey, getPublicWebConfig, importGuestProfileKey, listProfileKeys, refreshProfileKey, renameAccountProfile} from '../api/profileKeysApi'
import {useAuth} from '../auth/AuthProvider'
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
type RenameTarget = Profile | null

export function ProfileKeysPage() {
  const {t} = useTranslation()
  const {user} = useAuth()
  const navigate = useNavigate()
  const isGuest = user?.role === 'guest'
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [backendApiUrl, setBackendApiUrl] = useState('')
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [isBackendHelpVisible, setIsBackendHelpVisible] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const [isImportOpen, setIsImportOpen] = useState(false)
  const [importKey, setImportKey] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  const [renameTarget, setRenameTarget] = useState<RenameTarget>(null)
  const [renameName, setRenameName] = useState('')

  useEffect(() => {
    let cancelled = false
    listProfileKeys()
      .then((response) => {
        if (!cancelled) {
          setProfiles(Array.isArray(response.items) ? response.items : [])
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(t('account.profileKeys.loadError'))
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })
    getPublicWebConfig()
      .then((config) => {
        if (!cancelled) {
          setBackendApiUrl(config.backend_api_url)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setBackendApiUrl('')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const sortedProfiles = useMemo(() => (Array.isArray(profiles) ? [...profiles].sort((a, b) => a.id - b.id) : []), [profiles])

  function replaceProfile(nextProfile: Profile) {
    setProfiles((current) => current.map((profile) => (profile.id === nextProfile.id ? nextProfile : profile)))
  }

  function removeProfile(profileId: number) {
    setProfiles((current) => current.filter((profile) => profile.id !== profileId))
  }

  function profileName(profile: Profile) {
    return profile.display_name || t('account.profileKeys.profileTitle', {id: profile.id})
  }

  function openRenameDialog(profile: Profile) {
    setRenameTarget(profile)
    setRenameName(profile.display_name || '')
    setError(null)
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsBusy(true)
    try {
      const profile = await createProfileKey(createName.trim() || null)
      setProfiles((current) => [...current, profile])
      setCreateName('')
      setIsCreateOpen(false)
      setError(null)
    } catch (error) {
      if (error instanceof ApiError && error.code === 'active_profile_limit_exceeded') {
        setError(t('account.profileKeys.limitError'))
      } else {
        setError(t('account.profileKeys.createError'))
      }
    } finally {
      setIsBusy(false)
    }
  }

  async function handleConfirmAction() {
    if (!pendingAction) {
      return
    }
    const actionType = pendingAction.type
    setIsBusy(true)
    setError(null)
    try {
      if (pendingAction.type === 'refresh') {
        replaceProfile(await refreshProfileKey(pendingAction.profile.id))
      } else {
        await deleteProfileKey(pendingAction.profile.id)
        removeProfile(pendingAction.profile.id)
      }
      setPendingAction(null)
    } catch {
      setError(actionType === 'delete' ? t('account.profileKeys.deleteError') : t('account.profileKeys.refreshError'))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleImport(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsBusy(true)
    setImportError(null)
    try {
      const profile = await importGuestProfileKey(importKey.trim())
      setProfiles((current) => [...current, profile])
      setImportKey('')
      setIsImportOpen(false)
    } catch (caught) {
      if (caught instanceof ApiError) {
        const messages: Record<string, string> = {
          invalid_profile_key: t('account.profileKeys.importInvalidError'),
          profile_key_not_guest: t('account.profileKeys.importNotGuestError'),
          guest_profile_already_claimed: t('account.profileKeys.importClaimedError'),
          banned: t('account.profileKeys.importBannedError'),
          active_profile_limit_exceeded: t('account.profileKeys.limitError'),
        }
        setImportError((caught.code && messages[caught.code]) || t('account.profileKeys.importError'))
      } else {
        setImportError(t('account.profileKeys.importError'))
      }
    } finally {
      setIsBusy(false)
    }
  }

  async function handleRename(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!renameTarget) {
      return
    }
    setIsBusy(true)
    setError(null)
    try {
      replaceProfile(await renameAccountProfile(renameTarget.id, renameName.trim() || null))
      setRenameTarget(null)
      setRenameName('')
    } catch {
      setError(t('account.profileKeys.renameError'))
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <Box className="page-stack">
      <Box className="page-heading">
        <Box>
          <Text as="h1">{t('account.profileKeys.title')}</Text>
          <Text as="p">{t('account.profileKeys.description')}</Text>
        </Box>
        {!isGuest ? (
          <Box className="profile-heading-actions">
            <Button type="button" leadingVisual={KeyIcon} onClick={() => { setImportError(null); setIsImportOpen(true) }}>
              {t('account.profileKeys.importGuest')}
            </Button>
            <Button type="button" variant="primary" leadingVisual={PlusIcon} onClick={() => setIsCreateOpen(true)}>
              {t('account.profileKeys.newKey')}
            </Button>
          </Box>
        ) : null}
      </Box>

      {error ? <ErrorBanner message={error} /> : null}
      {isGuest ? (
        <Box className="guest-retention-notice" role="status">
          <KeyIcon size={18} />
          <Text as="p">{t('account.profileKeys.guestRetentionNotice', {days: sortedProfiles[0]?.guest_retention_days ?? 360})}</Text>
        </Box>
      ) : null}
      {isLoading ? <LoadingState /> : null}
      {!isLoading && sortedProfiles.length === 0 ? (
        <EmptyState title={t('account.profileKeys.emptyTitle')} message={t('account.profileKeys.emptyMessage')} />
      ) : null}

      {backendApiUrl ? (
        <Box className="panel compact-panel">
          <Box className="help-heading">
            <Text as="h2" sx={{fontSize: 2, m: 0}}>
              {t('account.profileKeys.backendApiUrl')}
            </Text>
            <Box className="inline-help">
              <button
                type="button"
                className="inline-help-trigger"
                aria-label={t('account.profileKeys.backendApiUrlHelpLabel')}
                aria-describedby={isBackendHelpVisible ? 'backend-api-url-help' : undefined}
                onMouseEnter={() => setIsBackendHelpVisible(true)}
                onMouseLeave={() => setIsBackendHelpVisible(false)}
                onFocus={() => setIsBackendHelpVisible(true)}
                onBlur={() => setIsBackendHelpVisible(false)}
              >
                <QuestionIcon size={14} />
              </button>
              {isBackendHelpVisible ? (
                <span id="backend-api-url-help" role="tooltip" className="inline-help-tooltip">
                  {t('account.profileKeys.backendApiUrlHelp')}
                </span>
              ) : null}
            </Box>
          </Box>
          <CopyableSecret value={backendApiUrl} copyLabel={t('account.profileKeys.copyBackendApiUrl')} />
        </Box>
      ) : null}

      <Box className="panel-list">
        {sortedProfiles.map((profile) => (
          <Box key={profile.id} className={`profile-row ${profile.revoked_at ? 'is-muted' : ''}`}>
            <Box className="row-icon">
              <KeyIcon size={20} />
            </Box>
            <Box className="row-main">
              <Box sx={{display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap'}}>
                <Text as="h2" sx={{fontSize: 2, m: 0}}>
                  {profile.display_name || t('account.profileKeys.profileTitle', {id: profile.id})}
                </Text>
                <StatusLabel status={profile.revoked_at ? 'revoked' : 'active'} />
              </Box>
              <Text as="p" sx={{color: 'fg.muted', my: 1}}>
                {t('account.profileKeys.profileId', {id: profile.id})} · {t('account.profileKeys.created')}{' '}
                <RelativeTime value={profile.created_at} /> · {t('account.profileKeys.lastUsed')} <RelativeTime value={profile.last_used_at} /> ·{' '}
                {t('account.profileKeys.lastUpload')} <RelativeTime value={profile.last_upload_at} />
              </Text>
              <CopyableSecret value={profile.profile_key} />
            </Box>
            <Box className="row-actions">
              <Button type="button" size="small" leadingVisual={FileDirectoryIcon} onClick={() => navigate(`/account/profiles/${profile.id}`)}>
                {t('account.profileKeys.viewFiles')}
              </Button>
              {!isGuest ? (
                <>
                  <Button
                    type="button"
                    size="small"
                    leadingVisual={PencilIcon}
                    aria-label={t('account.profileKeys.renameProfileFor', {name: profileName(profile)})}
                    onClick={() => openRenameDialog(profile)}
                  >
                    {t('account.profileKeys.renameProfile')}
                  </Button>
                  <Button
                    type="button"
                    size="small"
                    leadingVisual={SyncIcon}
                    aria-label={t('account.profileKeys.refreshKeyFor', {name: profile.display_name || profile.id})}
                    onClick={() => setPendingAction({type: 'refresh', profile})}
                    disabled={Boolean(profile.revoked_at)}
                  >
                    {t('account.profileKeys.refreshKey')}
                  </Button>
                  <Button
                    type="button"
                    size="small"
                    variant="danger"
                    leadingVisual={TrashIcon}
                    aria-label={t('account.profileKeys.deleteKeyFor', {name: profile.display_name || profile.id})}
                    onClick={() => setPendingAction({type: 'delete', profile})}
                  >
                    {t('account.profileKeys.deleteKey')}
                  </Button>
                </>
              ) : null}
            </Box>
          </Box>
        ))}
      </Box>

      {isCreateOpen ? (
        <form onSubmit={handleCreate}>
          <FormDialog
            title={t('account.profileKeys.createTitle')}
            submitText={t('account.profileKeys.createSubmit')}
            onCancel={() => setIsCreateOpen(false)}
            isBusy={isBusy}
          >
            <label className="field">
              <span>{t('account.profileKeys.displayName')}</span>
              <input
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                placeholder={t('account.profileKeys.displayNamePlaceholder')}
                autoFocus
              />
            </label>
          </FormDialog>
        </form>
      ) : null}

      {renameTarget ? (
        <form onSubmit={handleRename}>
          <FormDialog
            title={t('account.profileKeys.renameTitle', {name: profileName(renameTarget)})}
            submitText={t('account.profileKeys.renameSubmit')}
            onCancel={() => setRenameTarget(null)}
            isBusy={isBusy}
          >
            <label className="field">
              <span>{t('account.profileKeys.displayName')}</span>
              <input
                value={renameName}
                onChange={(event) => setRenameName(event.target.value)}
                placeholder={t('account.profileKeys.displayNamePlaceholder')}
                maxLength={255}
                autoFocus
              />
            </label>
          </FormDialog>
        </form>
      ) : null}

      {isImportOpen ? (
        <form onSubmit={handleImport}>
          <FormDialog
            title={t('account.profileKeys.importTitle')}
            submitText={t('account.profileKeys.importSubmit')}
            onCancel={() => { setImportError(null); setIsImportOpen(false) }}
            isBusy={isBusy}
          >
            {importError ? <ErrorBanner message={importError} /> : null}
            <label className="field">
              <span>{t('account.profileKeys.importKeyLabel')}</span>
              <input value={importKey} onChange={(event) => setImportKey(event.target.value)} required autoFocus autoComplete="off" />
            </label>
          </FormDialog>
        </form>
      ) : null}

      {pendingAction ? (
        <ConfirmDialog
          title={pendingAction.type === 'refresh' ? t('account.profileKeys.refreshTitle') : t('account.profileKeys.deleteTitle')}
          message={pendingAction.type === 'refresh' ? t('account.profileKeys.refreshMessage') : t('account.profileKeys.deleteMessage')}
          confirmText={pendingAction.type === 'refresh' ? t('account.profileKeys.refreshConfirm') : t('account.profileKeys.deleteConfirm')}
          onConfirm={handleConfirmAction}
          onCancel={() => setPendingAction(null)}
          isBusy={isBusy}
        />
      ) : null}
    </Box>
  )
}
