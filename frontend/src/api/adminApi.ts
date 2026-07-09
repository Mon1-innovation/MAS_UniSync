import {downloadBlob, request} from './client'
import type {
  AdminUserListItem,
  AuditLog,
  Backup,
  ListResponse,
  Profile,
  ProfileResponse,
  StatusResponse,
  StorageBucket,
  StorageBucketUsage,
  SystemSettings,
  SystemSettingsResponse,
  UserResponse,
  Version,
} from './types'

export function listAdminUsers() {
  return request<ListResponse<AdminUserListItem>>('/admin/users')
}

export function getAdminUser(userId: number) {
  return request<UserResponse>(`/admin/users/${userId}`)
}

export function getAdminProfile(profileId: number) {
  return request<ProfileResponse>(`/admin/profiles/${profileId}`)
}

export function banUser(userId: number, reason?: string) {
  return request<StatusResponse>(`/admin/users/${userId}/ban`, {
    method: 'POST',
    body: {reason: reason || null},
  })
}

export function unbanUser(userId: number) {
  return request<StatusResponse>(`/admin/users/${userId}/unban`, {method: 'POST'})
}

export function banProfile(profileId: number, reason?: string) {
  return request<StatusResponse>(`/admin/profiles/${profileId}/ban`, {
    method: 'POST',
    body: {reason: reason || null},
  })
}

export function unbanProfile(profileId: number) {
  return request<StatusResponse>(`/admin/profiles/${profileId}/unban`, {method: 'POST'})
}

export function banProfileKey(keyId: number, reason?: string) {
  return request<StatusResponse>(`/admin/profile-keys/${keyId}/ban`, {
    method: 'POST',
    body: {reason: reason || null},
  })
}

export function unbanProfileKey(keyId: number) {
  return request<StatusResponse>(`/admin/profile-keys/${keyId}/unban`, {method: 'POST'})
}

export function refreshAdminProfileKey(keyId: number) {
  return request<Profile>(`/admin/profile-keys/${keyId}/refresh`, {method: 'POST'})
}

export function deleteAdminProfileKey(keyId: number) {
  return request<void>(`/admin/profile-keys/${keyId}`, {method: 'DELETE'})
}

export function releaseAdminLock(lockIdOrProfileId: number) {
  return request<void>(`/admin/locks/${lockIdOrProfileId}/release`, {method: 'POST'})
}

export function restoreAdminBackup(profileId: number, backupId: number) {
  return request<Version>(`/admin/profiles/${profileId}/persistent/backups/${backupId}/restore`, {method: 'POST'})
}

export function getAdminCurrentPersistent(profileId: number) {
  return request<Version>(`/admin/profiles/${profileId}/persistent/current`)
}

export function downloadCurrentPersistent(profileId: number) {
  return downloadBlob(`/admin/profiles/${profileId}/persistent/current/download`)
}

export function listAdminBackups(profileId: number) {
  return request<ListResponse<Backup>>(`/admin/profiles/${profileId}/persistent/backups`)
}

export function downloadBackupPersistent(profileId: number, backupId: number) {
  return downloadBlob(`/admin/profiles/${profileId}/persistent/backups/${backupId}/download`)
}

export function listAuditLogs() {
  return request<ListResponse<AuditLog>>('/admin/audit-logs')
}

export function getAdminSettings() {
  return request<SystemSettingsResponse>('/admin/settings')
}

export function updateAdminSettings(settings: SystemSettings) {
  return request<SystemSettingsResponse>('/admin/settings', {
    method: 'PUT',
    body: {
      ...settings,
      storage_buckets: settings.storage_buckets?.map(storageBucketRequestBody),
    },
  })
}

export function testStorageBucket(bucket: StorageBucket) {
  return request<StatusResponse>('/admin/storage-buckets/test', {
    method: 'POST',
    body: storageBucketRequestBody(bucket),
  })
}

export function getStorageBucketUsage(bucketId: number) {
  return request<StorageBucketUsage>(`/admin/storage-buckets/${bucketId}/usage`)
}

export function deleteStorageBucket(bucketId: number) {
  return request<void>(`/admin/storage-buckets/${bucketId}?confirm=true`, {method: 'DELETE'})
}

function storageBucketRequestBody(bucket: StorageBucket) {
  return {
    id: bucket.id,
    name: bucket.name,
    type: bucket.type,
    is_active: bucket.is_active,
    space_budget_bytes: bucket.space_budget_bytes ?? null,
    config:
      bucket.type === 'webdav'
        ? {
            base_url: bucket.config.base_url ?? '',
            username: bucket.config.username ?? '',
            password: bucket.config.password ?? '',
            root_path: bucket.config.root_path ?? '',
          }
        : {
            path: bucket.config.path ?? '',
          },
  }
}
