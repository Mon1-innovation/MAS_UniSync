import {request} from './client'
import type {ListResponse, Profile} from './types'

export function listProfileKeys() {
  return request<ListResponse<Profile>>('/account/profile-keys')
}

export function createProfileKey(displayName: string | null) {
  return request<Profile>('/account/profile-keys', {
    method: 'POST',
    body: {display_name: displayName || null},
  })
}

export function refreshProfileKey(profileId: number) {
  return request<Profile>(`/account/profile-keys/${profileId}/refresh`, {method: 'POST'})
}

export function revokeProfileKey(profileId: number) {
  return request<Profile>(`/account/profile-keys/${profileId}/revoke`, {method: 'POST'})
}
