import {request} from './client'
import type {LoginResponse} from './types'

export function loginFlarum(identification: string, password: string) {
  return request<LoginResponse>('/login/flarum', {
    method: 'POST',
    body: {identification, password},
  })
}

export function loginGuest(profileKey: string) {
  return request<LoginResponse>('/login/guest', {
    method: 'POST',
    body: {profile_key: profileKey},
  })
}

export function logout() {
  return request<void>('/logout', {method: 'POST'})
}
