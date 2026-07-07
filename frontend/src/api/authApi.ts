import {request} from './client'
import type {LoginResponse} from './types'

export function loginFlarum(identification: string, password: string) {
  return request<LoginResponse>('/login/flarum', {
    method: 'POST',
    body: {identification, password},
  })
}

export function logout() {
  return request<void>('/logout', {method: 'POST'})
}
