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
}

export interface ProfileResponse {
  profile: Profile
}

export interface StatusResponse {
  status: string
}
