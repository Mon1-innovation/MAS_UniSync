import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {ApiError, downloadBlob, request} from './client'

const originalFetch = globalThis.fetch

describe('api request', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('includes credentials and serializes JSON bodies', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ok: true}), {
        status: 200,
        headers: {'Content-Type': 'application/json'},
      }),
    )

    await request('/account/profile-keys', {method: 'POST', body: {display_name: 'Main'}})

    expect(fetch).toHaveBeenCalledWith('/account/profile-keys', {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-cache'},
      body: JSON.stringify({display_name: 'Main'}),
    })
  })

  it('returns undefined for 204 responses', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, {status: 204}))

    await expect(request('/logout', {method: 'POST'})).resolves.toBeUndefined()
  })

  it('throws ApiError with parsed FastAPI detail codes', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({detail: {code: 'not_authenticated'}}), {
        status: 401,
        headers: {'Content-Type': 'application/json'},
      }),
    )

    await expect(request('/account/profile-keys')).rejects.toMatchObject({
      status: 401,
      code: 'not_authenticated',
    })
  })
})

describe('downloadBlob', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('downloads blobs with session credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('persistent', {status: 200}))

    const result = await downloadBlob('/admin/profiles/1/persistent/current/download')

    await expect(result.text()).resolves.toBe('persistent')
    expect(fetch).toHaveBeenCalledWith('/admin/profiles/1/persistent/current/download', {
      credentials: 'include',
    })
  })
})
