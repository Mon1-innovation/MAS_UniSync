import {render, screen, waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {MemoryRouter} from 'react-router-dom'
import {App} from './App'
import {i18n} from './i18n'
import type {User} from './api/types'

const adminUser: User = {
  id: 1,
  flarum_user_id: 10,
  username: 'admin',
  display_name: 'Admin User',
  avatar_url: 'https://example.test/admin.png',
  role: 'admin',
  last_login_at: '2026-07-07T08:00:00',
}

const normalUser: User = {
  ...adminUser,
  id: 2,
  flarum_user_id: 20,
  username: 'player',
  display_name: 'Player',
  role: 'user',
}

function mockFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Response | Promise<Response>) {
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(handler(input, init)))
}

function json(data: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: {'Content-Type': 'application/json'},
    ...init,
  })
}

function blob(data: string) {
  return new Response(data, {
    status: 200,
    headers: {'Content-Type': 'application/octet-stream'},
  })
}

function expectFetchCalled(path: string, options: Partial<RequestInit> = {}) {
  expect(fetch).toHaveBeenCalledWith(path, expect.objectContaining({credentials: 'include', ...options}))
}

describe('App', () => {
  beforeEach(async () => {
    localStorage.clear()
    await i18n.changeLanguage('zh')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('uses Chinese as the default language', async () => {
    mockFetch(() => json({detail: {code: 'not_found'}}, {status: 404}))

    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('button', {name: '登录'})).toBeInTheDocument()
  })

  it('switches to English and persists the language choice', async () => {
    mockFetch(() => json({detail: {code: 'not_found'}}, {status: 404}))
    const view = render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: 'English'}))
    expect(screen.getByRole('button', {name: 'Sign in'})).toBeInTheDocument()

    view.unmount()
    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('button', {name: 'Sign in'})).toBeInTheDocument()
    expect(localStorage.getItem('mas_unisync_language')).toBe('en')
  })

  it('logs in and redirects users to profile keys', async () => {
    mockFetch((input, init) => {
      if (input === '/login/flarum' && init?.method === 'POST') {
        return json({user: normalUser})
      }
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.type(screen.getByLabelText(/flarum 账号或邮箱/i), 'player')
    await userEvent.type(screen.getByLabelText(/密码/i), 'secret')
    await userEvent.click(screen.getByRole('button', {name: /登录/i}))

    await expect(screen.findByRole('heading', {level: 1, name: /Profile Key/i})).resolves.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('mas_unisync_user') || '{}')).toMatchObject({username: 'player'})
  })

  it('shows invalid credential errors', async () => {
    mockFetch((input) => {
      if (input === '/login/flarum') {
        return json({detail: {code: 'invalid_flarum_credentials'}}, {status: 401})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.type(screen.getByLabelText(/flarum 账号或邮箱/i), 'player')
    await userEvent.type(screen.getByLabelText(/密码/i), 'bad')
    await userEvent.click(screen.getByRole('button', {name: /登录/i}))

    await expect(screen.findByText(/flarum 凭据无效/i)).resolves.toBeInTheDocument()
  })

  it('hides admin navigation for non-admin users', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByRole('heading', {name: /Profile Key/i})).toBeInTheDocument())
    expect(screen.queryByRole('link', {name: /^admin$/i})).not.toBeInTheDocument()
  })

  it('logs out and clears the cached user', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input, init) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/logout' && init?.method === 'POST') {
        return new Response(null, {status: 204})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /退出登录/i}))

    await expect(screen.findByRole('button', {name: /登录/i})).resolves.toBeInTheDocument()
    expect(localStorage.getItem('mas_unisync_user')).toBeNull()
  })

  it('creates profile keys with the submitted display name', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    let submittedBody: unknown
    mockFetch(async (input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({items: []})
      }
      if (input === '/account/profile-keys' && init?.method === 'POST') {
        submittedBody = JSON.parse(String(init.body))
        return json(
          {
            id: 10,
            user_id: 2,
            display_name: 'Laptop',
            profile_key: 'maspk_created',
            revoked_at: null,
            last_used_at: null,
            last_upload_at: null,
            created_at: '2026-07-07T08:00:00',
          },
          {status: 201},
        )
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /新建 Profile Key/i}))
    await userEvent.type(screen.getByLabelText(/显示名称/i), 'Laptop')
    await userEvent.click(screen.getByRole('button', {name: /创建 Key/i}))

    await expect(screen.findByText('maspk_created')).resolves.toBeInTheDocument()
    expect(submittedBody).toEqual({display_name: 'Laptop'})
  })

  it('shows a specific error when profile key creation reaches the account limit', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch(async (input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({items: []})
      }
      if (input === '/v1/config/web-url') {
        return json({
          backend_api_url: 'https://api.example.test',
          frontend_web_url: 'https://portal.example.test',
          profile_keys_url: 'https://portal.example.test/account/profile-keys',
        })
      }
      if (input === '/account/profile-keys' && init?.method === 'POST') {
        return json({detail: {code: 'active_profile_limit_exceeded'}}, {status: 409})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /新建 Profile Key/i}))
    await userEvent.type(screen.getByLabelText(/显示名称/i), 'Laptop')
    await userEvent.click(screen.getByRole('button', {name: /创建 Key/i}))

    await expect(screen.findByText('已达到当前账户可用 Profile 数量上限。')).resolves.toBeInTheDocument()
  })

  it('shows the configured backend API URL on the profile keys page', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/v1/config/web-url') {
        return json({
          backend_api_url: 'https://api.example.test',
          frontend_web_url: 'https://portal.example.test',
          profile_keys_url: 'https://portal.example.test/account/profile-keys',
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByText('Backend API URL')).resolves.toBeInTheDocument()
    expect(screen.queryByText('将这个链接填写至你的 API Key 界面的 MAS UniSync API URL。')).not.toBeInTheDocument()
    await userEvent.hover(screen.getByRole('button', {name: 'Backend API URL 说明'}))
    expect(screen.getByText('将这个链接填写至你的 API Key 界面的 MAS UniSync API URL。')).toBeInTheDocument()
    expect(screen.getByText('https://api.example.test')).toBeInTheDocument()
  })

  it('renders access denied when the admin API returns 403', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/users') {
        return json({detail: {code: 'admin_required'}}, {status: 403})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/users']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByText(/(does not have access to the admin area|没有权限访问管理区域)/i)).resolves.toBeInTheDocument()
    expect(screen.queryByRole('link', {name: /^admin$/i})).not.toBeInTheDocument()
  })

  it('renders profiles on admin user detail and links to profile detail', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    const profile = {
      id: 11,
      user_id: 2,
      display_name: 'Desktop',
      profile_key: 'maspk_desktop',
      revoked_at: null,
      last_used_at: '2026-07-07T08:30:00',
      last_upload_at: '2026-07-07T09:00:00',
      created_at: '2026-07-07T08:00:00',
    }
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/users/2') {
        return json({user: normalUser, profiles: [profile]})
      }
      if (input === '/admin/profiles/11') {
        return json({profile})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/users/2']}>
        <App />
      </MemoryRouter>,
    )

    const link = await screen.findByRole('link', {name: /desktop/i})
    expect(link).toHaveAttribute('href', '/admin/profiles/11')
    expect(screen.queryByRole('heading', {name: /^profiles$/i})).not.toBeInTheDocument()
    expect(screen.getByText('启用')).toBeInTheDocument()
    expect(document.querySelector('time[datetime="2026-07-07T08:00:00"]')).toBeInTheDocument()
    expect(document.querySelector('time[datetime="2026-07-07T08:30:00"]')).toBeInTheDocument()
    expect(document.querySelector('time[datetime="2026-07-07T09:00:00"]')).toBeInTheDocument()

    await userEvent.click(link)
    await waitFor(() => {
      expectFetchCalled('/admin/profiles/11')
    })
  })

  it('keeps admin user detail visible when profiles are missing from the response', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/users/2') {
        return json({user: normalUser})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/users/2']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findAllByText('Player')).resolves.not.toHaveLength(0)
    expect(screen.getByText(/(No profiles|没有 Profile)/i)).toBeInTheDocument()
  })

  it('updates a refreshed profile key and removes deleted rows', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({
          items: [
            {
              id: 9,
              user_id: 2,
              display_name: 'Main',
              profile_key: 'maspk_old',
              revoked_at: null,
              last_used_at: null,
              last_upload_at: null,
              created_at: '2026-07-07T08:00:00',
            },
          ],
        })
      }
      if (input === '/account/profile-keys/9/refresh') {
        return json({
          id: 9,
          user_id: 2,
          display_name: 'Main',
          profile_key: 'maspk_new',
          revoked_at: null,
          last_used_at: null,
          last_upload_at: null,
          created_at: '2026-07-07T08:00:00',
        })
      }
      if (input === '/account/profile-keys/9' && init?.method === 'DELETE') {
        return new Response(null, {status: 204})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByText('maspk_old')).resolves.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', {name: /(refresh key|刷新 .+ 的 Key)/i}))
    await userEvent.click(await screen.findByRole('button', {name: /^(refresh|刷新)$/i}))
    await expect(screen.findByText('maspk_new')).resolves.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', {name: /(delete key|删除 .+ 的 Key)/i}))
    expect(screen.getByText(/persistent 文件将被删除/i)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', {name: /^(delete|删除)$/i}))

    await waitFor(() => expect(screen.queryByText('Main')).not.toBeInTheDocument())
    expect(screen.getByText('没有 Profile Key')).toBeInTheDocument()
    expectFetchCalled('/account/profile-keys/9', {method: 'DELETE'})
  })

  it('allows revoked profile keys to be deleted from the account page', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({
          items: [
            {
              id: 9,
              user_id: 2,
              display_name: 'Old key',
              profile_key: 'maspk_old',
              revoked_at: '2026-07-07T08:10:00',
              last_used_at: null,
              last_upload_at: null,
              created_at: '2026-07-07T08:00:00',
            },
          ],
        })
      }
      if (input === '/account/profile-keys/9' && init?.method === 'DELETE') {
        return new Response(null, {status: 204})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    const deleteButton = await screen.findByRole('button', {name: /(delete key|删除 .+ 的 Key)/i})
    expect(deleteButton).toBeEnabled()
    await userEvent.click(deleteButton)
    await userEvent.click(await screen.findByRole('button', {name: /^(delete|删除)$/i}))

    await waitFor(() => expect(screen.queryByText('Old key')).not.toBeInTheDocument())
    expectFetchCalled('/account/profile-keys/9', {method: 'DELETE'})
  })

  it('shows an error when account profile key deletion fails', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({
          items: [
            {
              id: 9,
              user_id: 2,
              display_name: 'Main',
              profile_key: 'maspk_main',
              revoked_at: null,
              last_used_at: null,
              last_upload_at: null,
              created_at: '2026-07-07T08:00:00',
            },
          ],
        })
      }
      if (input === '/account/profile-keys/9' && init?.method === 'DELETE') {
        return json({detail: {code: 'delete_failed'}}, {status: 500})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /(delete key|删除 .+ 的 Key)/i}))
    const confirmButton = await screen.findByRole('button', {name: /^(delete|删除)$/i})
    await userEvent.click(confirmButton)

    await expect(screen.findByText(/(could not delete this profile key|无法删除这个 Profile Key)/i)).resolves.toBeInTheDocument()
    expect(confirmButton).toBeEnabled()
    expect(screen.getByText('Main')).toBeInTheDocument()
  })

  it('deletes an admin profile key and returns to the owning user detail', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    const profile = {
      id: 9,
      user_id: 2,
      display_name: 'Main',
      profile_key: 'maspk_main',
      revoked_at: null,
      last_used_at: null,
      last_upload_at: null,
      created_at: '2026-07-07T08:00:00',
    }
    mockFetch((input, init) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/profiles/9') {
        return json({profile})
      }
      if (input === '/admin/profiles/9/persistent/current') {
        return json({detail: {code: 'no_current_persistent'}}, {status: 404})
      }
      if (input === '/admin/profiles/9/persistent/backups') {
        return json({items: []})
      }
      if (input === '/admin/profile-keys/9' && init?.method === 'DELETE') {
        return new Response(null, {status: 204})
      }
      if (input === '/admin/users/2') {
        return json({user: normalUser, profiles: []})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/profiles/9']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByRole('heading', {level: 1, name: 'Main'})).resolves.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', {name: /(delete key|删除 Key)/i}))
    await userEvent.click(await screen.findByRole('button', {name: /^(delete this key|删除这个 Key)$/i}))

    await expect(screen.findAllByText('Player')).resolves.not.toHaveLength(0)
    expectFetchCalled('/admin/profile-keys/9', {method: 'DELETE'})
  })

  it('shows an error when admin profile key deletion fails', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    const profile = {
      id: 9,
      user_id: 2,
      display_name: 'Main',
      profile_key: 'maspk_main',
      revoked_at: null,
      last_used_at: null,
      last_upload_at: null,
      created_at: '2026-07-07T08:00:00',
    }
    mockFetch((input, init) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/profiles/9') {
        return json({profile})
      }
      if (input === '/admin/profiles/9/persistent/current') {
        return json({detail: {code: 'no_current_persistent'}}, {status: 404})
      }
      if (input === '/admin/profiles/9/persistent/backups') {
        return json({items: []})
      }
      if (input === '/admin/profile-keys/9' && init?.method === 'DELETE') {
        return json({detail: {code: 'delete_failed'}}, {status: 500})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/profiles/9']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /(delete key|删除 Key)/i}))
    const confirmButton = await screen.findByRole('button', {name: /^(delete this key|删除这个 Key)$/i})
    await userEvent.click(confirmButton)

    await expect(screen.findByText(/(could not delete this profile key|无法删除这个 Profile Key)/i)).resolves.toBeInTheDocument()
    expect(confirmButton).toBeEnabled()
    expect(screen.getByRole('heading', {level: 1, name: 'Main'})).toBeInTheDocument()
  })

  it('allows revoked profile keys to be deleted from the admin profile page', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    const profile = {
      id: 9,
      user_id: 2,
      display_name: 'Old key',
      profile_key: 'maspk_old',
      revoked_at: '2026-07-07T08:10:00',
      last_used_at: null,
      last_upload_at: null,
      created_at: '2026-07-07T08:00:00',
    }
    mockFetch((input, init) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/profiles/9') {
        return json({profile})
      }
      if (input === '/admin/profiles/9/persistent/current') {
        return json({detail: {code: 'no_current_persistent'}}, {status: 404})
      }
      if (input === '/admin/profiles/9/persistent/backups') {
        return json({items: []})
      }
      if (input === '/admin/profile-keys/9' && init?.method === 'DELETE') {
        return new Response(null, {status: 204})
      }
      if (input === '/admin/users/2') {
        return json({user: normalUser, profiles: []})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/profiles/9']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByRole('heading', {level: 1, name: 'Old key'})).resolves.toBeInTheDocument()
    const deleteButton = screen.getByRole('button', {name: /(delete key|删除 Key)/i})
    expect(deleteButton).toBeEnabled()
    await userEvent.click(deleteButton)
    await userEvent.click(await screen.findByRole('button', {name: /^(delete this key|删除这个 Key)$/i}))

    await expect(screen.findAllByText('Player')).resolves.not.toHaveLength(0)
    expectFetchCalled('/admin/profile-keys/9', {method: 'DELETE'})
  })

  it('shows current persistent metadata and lists backups directly on the admin profile page', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:download'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const profile = {
      id: 9,
      user_id: 2,
      display_name: 'Main',
      profile_key: 'maspk_main',
      revoked_at: null,
      last_used_at: '2026-07-07T08:30:00',
      last_upload_at: '2026-07-07T09:00:00',
      created_at: '2026-07-07T08:00:00',
      storage_usage: 12,
      storage_limit: 24,
    }
    mockFetch((input, init) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/profiles/9') {
        return json({profile})
      }
      if (input === '/admin/profiles/9/persistent/current') {
        return json({
          id: 22,
          profile_id: 9,
          sha256: 'sha-current',
          size: 12,
          renpy_version: '8.2.3',
          mas_version: '0.12.15',
          created_at: '2026-07-07T09:00:00',
        })
      }
      if (input === '/admin/profiles/9/persistent/backups') {
        return json({
          items: [
            {
              id: 5,
              backup_date: '2026-07-07',
              version_id: 22,
              profile_id: 9,
              sha256: 'sha-backup',
              size: 12,
              renpy_version: '8.2.3',
              mas_version: '0.12.15',
              created_at: '2026-07-07T09:00:00',
            },
          ],
        })
      }
      if (input === '/admin/profiles/9/persistent/backups/5/download') {
        return blob('backup-bytes')
      }
      if (input === '/admin/profiles/9/persistent/current/download') {
        return blob('current-bytes')
      }
      if (input === '/admin/profiles/9/persistent/backups/5/restore' && init?.method === 'POST') {
        return json({
          id: 22,
          profile_id: 9,
          sha256: 'sha-backup',
          size: 12,
          renpy_version: '8.2.3',
          mas_version: '0.12.15',
          created_at: '2026-07-07T09:00:00',
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/profiles/9']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByRole('heading', {level: 1, name: 'Main'})).resolves.toBeInTheDocument()
    expect(screen.getByText(/(Profile file size|Profile 文件大小)/i)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', {name: /存储用量/i})).toHaveAttribute('aria-valuenow', '50')
    expect(screen.getByText(/(Current persistent|当前 persistent)/i)).toBeInTheDocument()
    expect(screen.getByText(/(version #22|版本 #22)/i)).toBeInTheDocument()
    expect(screen.getAllByText('12 B').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('sha-current')).toBeInTheDocument()
    expect(await screen.findByText('2026-07-07')).toBeInTheDocument()
    expect(screen.getByText('sha-backup')).toBeInTheDocument()
    expect(screen.queryByLabelText(/backup id/i)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', {name: /(download current|下载当前文件)/i}))
    await userEvent.click(screen.getByRole('button', {name: /(download backup 2026-07-07|下载 2026-07-07 的备份)/i}))
    await userEvent.click(screen.getByRole('button', {name: /(restore backup 2026-07-07|恢复 2026-07-07 的备份)/i}))

    expectFetchCalled('/admin/profiles/9/persistent/current')
    expectFetchCalled('/admin/profiles/9/persistent/current/download')
    expectFetchCalled('/admin/profiles/9/persistent/backups')
    expectFetchCalled('/admin/profiles/9/persistent/backups/5/download')
    expectFetchCalled('/admin/profiles/9/persistent/backups/5/restore', {method: 'POST'})
  })

  it('shows an empty current persistent state on the admin profile page', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    const profile = {
      id: 9,
      user_id: 2,
      display_name: 'Main',
      profile_key: 'maspk_main',
      revoked_at: null,
      last_used_at: null,
      last_upload_at: null,
      created_at: '2026-07-07T08:00:00',
      storage_usage: 0,
    }
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/profiles/9') {
        return json({profile})
      }
      if (input === '/admin/profiles/9/persistent/current') {
        return json({detail: {code: 'no_current_persistent'}}, {status: 404})
      }
      if (input === '/admin/profiles/9/persistent/backups') {
        return json({items: []})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/profiles/9']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByRole('heading', {level: 1, name: 'Main'})).resolves.toBeInTheDocument()
    expect(screen.getByText(/(No current persistent|没有当前 persistent)/i)).toBeInTheDocument()
    expect(screen.getByText(/(does not have an uploaded persistent file yet|还没有上传 persistent 文件)/i)).toBeInTheDocument()
    expect(screen.queryByText(/(could not load this profile|无法加载这个 Profile)/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: /(download current|下载当前文件)/i})).not.toBeInTheDocument()
  })

  it('links profile keys to owned persistent files and downloads them', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:download'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    mockFetch((input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({
          items: [
            {
              id: 9,
              user_id: 2,
              display_name: 'Main',
              profile_key: 'maspk_main',
              revoked_at: null,
              last_used_at: '2026-07-07T08:30:00',
              last_upload_at: '2026-07-07T09:00:00',
              created_at: '2026-07-07T08:00:00',
              storage_usage: 12,
              storage_limit: 24,
            },
          ],
        })
      }
      if (input === '/account/profiles/9') {
        return json({
          profile: {
            id: 9,
            user_id: 2,
            display_name: 'Main',
            profile_key: 'maspk_main',
            revoked_at: null,
            last_used_at: '2026-07-07T08:30:00',
            last_upload_at: '2026-07-07T09:00:00',
            created_at: '2026-07-07T08:00:00',
            storage_usage: 12,
            storage_limit: 24,
            lock_status: 'active',
          },
        })
      }
      if (input === '/account/profiles/9/persistent/current') {
        return json({
          id: 22,
          profile_id: 9,
          sha256: 'sha-current',
          size: 12,
          renpy_version: '8.2.3',
          mas_version: '0.12.15',
          created_at: '2026-07-07T09:00:00',
        })
      }
      if (input === '/account/profiles/9/persistent/backups') {
        return json({
          items: [
            {
              id: 5,
              backup_date: '2026-07-07',
              version_id: 22,
              profile_id: 9,
              sha256: 'sha-backup',
              size: 12,
              renpy_version: '8.2.3',
              mas_version: '0.12.15',
              created_at: '2026-07-07T09:00:00',
            },
          ],
        })
      }
      if (input === '/account/profiles/9/lock/release' && init?.method === 'POST') {
        return new Response(null, {status: 204})
      }
      if (input === '/account/profiles/9/persistent/current/download') {
        return blob('current-bytes')
      }
      if (input === '/account/profiles/9/persistent/backups/5/download') {
        return blob('backup-bytes')
      }
      if (input === '/account/profiles/9/persistent/backups/5/restore' && init?.method === 'POST') {
        return json({
          id: 33,
          profile_id: 9,
          sha256: 'sha-backup',
          size: 12,
          renpy_version: '8.2.3',
          mas_version: '0.12.15',
          created_at: '2026-07-07T09:00:00',
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    const filesButton = await screen.findByRole('button', {name: /(view files|查看文件)/i})
    await userEvent.click(filesButton)

    await expect(screen.findByRole('heading', {level: 1, name: 'Main'})).resolves.toBeInTheDocument()
    expect(screen.getByText(/(Profile file size|Profile 文件大小)/i)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', {name: /存储用量/i})).toHaveAttribute('aria-valuenow', '50')
    expect(screen.getByText((_content, element) => element?.textContent === '12 B / 24 B')).toBeInTheDocument()
    expect(screen.getAllByText('12 B').length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText('sha-current')).not.toBeInTheDocument()
    expect(screen.getByText(/(Lock status|锁状态)/i)).toBeInTheDocument()
    expect(screen.getByText(/(locked|已锁定)/i)).toBeInTheDocument()
    expect(screen.getByRole('button', {name: /^(unlock|解锁)$/i})).toBeInTheDocument()
    expect(screen.getByText('2026-07-07')).toBeInTheDocument()
    expect(screen.getByText('sha-backup')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', {name: /^(unlock|解锁)$/i}))
    await waitFor(() => expect(screen.getAllByRole('button', {name: /^(unlock|解锁)$/i})).toHaveLength(2))
    await userEvent.click(screen.getAllByRole('button', {name: /^(unlock|解锁)$/i})[1])

    await waitFor(() => expect(screen.getByText(/(unlocked|未锁定)/i)).toBeInTheDocument())
    expect(screen.queryByRole('button', {name: /^(unlock|解锁)$/i})).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', {name: /(download current|下载当前文件)/i}))
    await userEvent.click(screen.getByRole('button', {name: /(download backup 2026-07-07|下载 2026-07-07 的备份)/i}))
    await userEvent.click(screen.getByRole('button', {name: /(restore backup 2026-07-07|恢复 2026-07-07 的备份)/i}))

    expectFetchCalled('/account/profiles/9/lock/release', {method: 'POST'})
    expectFetchCalled('/account/profiles/9/persistent/current/download')
    expectFetchCalled('/account/profiles/9/persistent/backups/5/download')
    expectFetchCalled('/account/profiles/9/persistent/backups/5/restore', {method: 'POST'})
    await waitFor(() => expect(screen.getByText(/(version #33|版本 #33)/i)).toBeInTheDocument())
  })

  it('shows an empty current file state for profiles without persistent uploads', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/account/profiles/10') {
        return json({
          profile: {
            id: 10,
            user_id: 2,
            display_name: 'Fresh profile',
            profile_key: 'maspk_empty',
            revoked_at: null,
            last_used_at: null,
            last_upload_at: null,
            created_at: '2026-07-07T08:00:00',
          },
        })
      }
      if (input === '/account/profiles/10/persistent/current') {
        return json({detail: {code: 'no_current_persistent'}}, {status: 404})
      }
      if (input === '/account/profiles/10/persistent/backups') {
        return json({items: []})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profiles/10']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByRole('heading', {level: 1, name: 'Fresh profile'})).resolves.toBeInTheDocument()
    expect(screen.getByText('maspk_empty')).toBeInTheDocument()
    expect(screen.getByText(/(no current persistent|没有当前 persistent)/i)).toBeInTheDocument()
    expect(screen.queryByText(/could not load this profile/i)).not.toBeInTheDocument()
  })

  it('shows a specific message when an account profile is not owned by the user', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/account/profiles/1') {
        return json({detail: {code: 'profile_not_found'}}, {status: 404})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profiles/1']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByText(/你的账户下没有这个 Profile/i)).resolves.toBeInTheDocument()
    expect(screen.queryByText(/could not load this profile/i)).not.toBeInTheDocument()
  })

  it('links audit target profile ids to profile detail routes', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/audit-logs') {
        return json({
          items: [
            {
              id: 1,
              actor_user_id: 1,
              actor_role: 'admin',
              action: 'admin.profile.ban',
              target_user_id: 2,
              target_profile_id: 42,
              target_profile_key_id: 42,
              ip_address: '127.0.0.1',
              user_agent: 'test',
              created_at: '2026-07-07T08:00:00',
            },
          ],
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/audit-logs']}>
        <App />
      </MemoryRouter>,
    )

    const link = await screen.findByRole('link', {name: '#42'})
    expect(link).toHaveAttribute('href', '/admin/profiles/42')
  })

  it('allows admins to edit runtime system settings', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    let submittedBody: unknown
    mockFetch((input, init) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/admin/settings' && !init?.method) {
        return json({
          settings: {
            backend_api_url: 'https://api.example.test',
            frontend_web_url: 'https://portal.example.test',
            profile_storage_limit_bytes: 10485760,
            max_active_profiles_per_account: 3,
          },
        })
      }
      if (input === '/admin/settings' && init?.method === 'PUT') {
        submittedBody = JSON.parse(String(init.body))
        return json({
          settings: {
            backend_api_url: 'https://api2.example.test',
            frontend_web_url: 'https://portal.example.test',
            profile_storage_limit_bytes: 20971520,
            max_active_profiles_per_account: 4,
          },
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/settings']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByRole('heading', {level: 1, name: /(settings|设置)/i})).resolves.toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText(/backend api url/i))
    await userEvent.type(screen.getByLabelText(/backend api url/i), 'https://api2.example.test')
    await userEvent.clear(screen.getByLabelText(/(profile storage limit|Profile 存储上限)/i))
    await userEvent.type(screen.getByLabelText(/(profile storage limit|Profile 存储上限)/i), '20971520')
    await userEvent.clear(screen.getByLabelText(/(max active profiles|最大启用 Profile 数)/i))
    await userEvent.type(screen.getByLabelText(/(max active profiles|最大启用 Profile 数)/i), '4')
    await userEvent.click(screen.getByRole('button', {name: /(save settings|保存设置)/i}))

    await expect(screen.findByText(/(settings saved|设置已保存)/i)).resolves.toBeInTheDocument()
    expect(submittedBody).toEqual({
      backend_api_url: 'https://api2.example.test',
      frontend_web_url: 'https://portal.example.test',
      profile_storage_limit_bytes: 20971520,
      max_active_profiles_per_account: 4,
    })
  })
})
