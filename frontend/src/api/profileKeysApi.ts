import {downloadBlob, downloadBlobWithFilename, request} from './client'
import type {Backup, ListResponse, Profile, ProfileResponse, PublicWebConfig, Version} from './types'

export function listProfileKeys() {
  return request<ListResponse<Profile>>('/account/profile-keys')
}

export function getPublicWebConfig() {
  return request<PublicWebConfig>('/v1/config/web-url')
}

export function createProfileKey(displayName: string | null) {
  return request<Profile>('/account/profile-keys', {
    method: 'POST',
    body: {display_name: displayName || null},
  })
}

export function importGuestProfileKey(profileKey: string) {
  return request<Profile>('/account/profile-keys/import-guest', {
    method: 'POST',
    body: {profile_key: profileKey},
  })
}

export function renameAccountProfile(profileId: number, displayName: string | null) {
  return request<Profile>(`/account/profiles/${profileId}`, {
    method: 'PATCH',
    body: {display_name: displayName || null},
  })
}

export function refreshProfileKey(profileId: number) {
  return request<Profile>(`/account/profile-keys/${profileId}/refresh`, {method: 'POST'})
}

export function deleteProfileKey(profileId: number) {
  return request<void>(`/account/profile-keys/${profileId}`, {method: 'DELETE'})
}

export function getAccountProfile(profileId: number) {
  return request<ProfileResponse>(`/account/profiles/${profileId}`)
}

export function getAccountCurrentPersistent(profileId: number) {
  return request<Version>(`/account/profiles/${profileId}/persistent/current`)
}

export function listAccountBackups(profileId: number) {
  return request<ListResponse<Backup>>(`/account/profiles/${profileId}/persistent/backups`)
}

export function releaseAccountProfileLock(profileId: number) {
  return request<void>(`/account/profiles/${profileId}/lock/release`, {method: 'POST'})
}

export function downloadAccountCurrentPersistent(profileId: number) {
  return downloadBlob(`/account/profiles/${profileId}/persistent/current/download`)
}

export function downloadAccountBackupPersistent(profileId: number, backupId: number) {
  return downloadBlob(`/account/profiles/${profileId}/persistent/backups/${backupId}/download`)
}

export function restoreAccountBackup(profileId: number, backupId: number) {
  return request<Version>(`/account/profiles/${profileId}/persistent/backups/${backupId}/restore`, {method: 'POST'})
}

export function downloadLatestClientRelease() {
  return downloadBlobWithFilename('/account/client-release/latest/download')
}
