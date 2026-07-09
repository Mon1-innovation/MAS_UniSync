export type UserRole = 'admin' | 'user'

export interface User {
  id: number
  flarum_user_id: number
  username: string
  display_name: string | null
  avatar_url: string | null
  role: UserRole
  last_login_at: string | null
}

export interface AdminUserListItem extends User {
  profile_count: number
  storage_usage: number
  last_upload_at: string | null
  last_submod_use: string | null
  lock_status: 'active' | 'none' | string
  ban_status: 'active' | 'none' | string
}

export interface Profile {
  id: number
  user_id: number
  display_name: string | null
  profile_key: string
  storage_usage: number
  storage_limit: number
  lock_status: 'active' | 'none' | string
  revoked_at: string | null
  last_used_at: string | null
  last_upload_at: string | null
  created_at: string
}

export interface Version {
  id: number
  profile_id: number
  sha256: string
  size: number
  renpy_version: string | null
  mas_version: string | null
  created_at: string
}

export interface Backup {
  id: number
  backup_date: string
  version_id: number
  profile_id: number
  sha256: string
  size: number
  renpy_version: string | null
  mas_version: string | null
  created_at: string
}

export interface AuditLog {
  id: number
  actor_user_id: number | null
  actor_role: UserRole | string | null
  action: string
  target_user_id: number | null
  target_profile_id: number | null
  target_profile_key_id: number | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

export interface ListResponse<T> {
  items: T[]
}

export interface LoginResponse {
  user: User
}

export interface UserResponse {
  user: User
  profiles: Profile[]
}

export interface ProfileResponse {
  profile: Profile
}

export interface StatusResponse {
  status: string
}

export interface SystemSettings {
  backend_api_url: string
  frontend_web_url: string
  profile_storage_limit_bytes: number
  max_active_profiles_per_account: number
  active_storage_bucket_id: number | null
  storage_buckets: StorageBucket[]
}

export interface SystemSettingsResponse {
  settings: SystemSettings
}

export type StorageBucketType = 'local' | 'webdav'

export interface StorageBucket {
  id?: number
  name: string
  type: StorageBucketType
  is_active: boolean
  config: {
    path?: string
    base_url?: string
    username?: string
    password?: string
    root_path?: string
    has_password?: boolean
  }
}

export interface PublicWebConfig {
  backend_api_url: string
  frontend_web_url: string
  profile_keys_url: string
}
