import {render, screen, waitFor, within} from '@testing-library/react'
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

const guestUser: User = {
  ...normalUser,
  id: 3,
  flarum_user_id: 'guest:3',
  username: 'guest-3',
  display_name: 'Guest',
  role: 'guest',
}

const githubRepositoryUrl = 'https://github.com/Mon1-innovation/MAS_UniSync'

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

  it('does not show the GitHub repository link on the login page', async () => {
    mockFetch(() => json({detail: {code: 'not_found'}}, {status: 404}))

    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    await screen.findByRole('button', {name: '登录'})
    expect(screen.queryByRole('link', {name: 'GitHub repository'})).not.toBeInTheDocument()
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

  it('logs in with a guest key and hides profile mutation controls', async () => {
    let submittedBody: unknown
    const guestProfile = {
      id: 30,
      user_id: 3,
      display_name: 'Guest',
      profile_key: 'maspk_guest',
      storage_usage: 0,
      storage_limit: 10485760,
      lock_status: 'none',
      revoked_at: null,
      last_used_at: '2026-07-10T08:00:00Z',
      last_upload_at: null,
      created_at: '2026-07-10T08:00:00Z',
      is_guest: true,
      guest_retention_days: 360,
      guest_expires_at: '2027-07-05T08:00:00Z',
    }
    mockFetch((input, init) => {
      if (input === '/login/guest' && init?.method === 'POST') {
        submittedBody = JSON.parse(String(init.body))
        return json({user: guestUser})
      }
      if (input === '/account/profile-keys') {
        return json({items: [guestProfile]})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByRole('button', {name: /游客 Key/i}))
    await userEvent.type(screen.getByLabelText(/^Profile Key$/i), 'maspk_guest')
    await userEvent.click(screen.getByRole('button', {name: /使用游客 Key 登录/i}))

    await expect(screen.findByText(/长期未使用.*删除.*云端存档/i)).resolves.toBeInTheDocument()
    expect(submittedBody).toEqual({profile_key: 'maspk_guest'})
    expect(screen.queryByRole('button', {name: /新建 Profile Key/i})).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: /导入游客 Key/i})).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: /刷新.*Key/i})).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: /删除.*Key/i})).not.toBeInTheDocument()
    expect(screen.getByRole('button', {name: /查看文件/i})).toBeInTheDocument()
  })

  it('shows the GitHub repository link in the authenticated header', async () => {
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

    await screen.findByRole('heading', {level: 1, name: /Profile Key/i})
    const repositoryLink = screen.getByRole('link', {name: 'GitHub repository'})
    expect(repositoryLink).toHaveAttribute('href', githubRepositoryUrl)
    expect(repositoryLink).toHaveAttribute('target', '_blank')
    expect(repositoryLink).toHaveAttribute('rel', 'noreferrer')
  })

  it('imports a guest key into a Flarum account', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    let submittedBody: unknown
    mockFetch((input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({items: []})
      }
      if (input === '/account/profile-keys/import-guest' && init?.method === 'POST') {
        submittedBody = JSON.parse(String(init.body))
        return json({
          id: 31,
          user_id: 2,
          display_name: 'Guest',
          profile_key: 'maspk_imported',
          storage_usage: 128,
          storage_limit: 10485760,
          lock_status: 'active',
          revoked_at: null,
          last_used_at: '2026-07-10T08:00:00Z',
          last_upload_at: '2026-07-10T08:00:00Z',
          created_at: '2026-07-09T08:00:00Z',
          is_guest: false,
          guest_retention_days: null,
          guest_expires_at: null,
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /导入游客 Key/i}))
    await userEvent.type(screen.getByLabelText(/^游客 Profile Key$/i), 'maspk_imported')
    await userEvent.click(screen.getByRole('button', {name: /^导入$/i}))

    await expect(screen.findByText('maspk_imported')).resolves.toBeInTheDocument()
    expect(submittedBody).toEqual({profile_key: 'maspk_imported'})
  })

  it.each([
    ['invalid_profile_key', '游客 Key 无效'],
    ['profile_key_not_guest', '不是游客 Key'],
    ['guest_profile_already_claimed', '已经被认领'],
    ['banned', '已被封禁'],
    ['active_profile_limit_exceeded', '数量上限'],
  ])('shows a specific guest import error for %s', async (code, message) => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    mockFetch((input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({items: []})
      }
      if (input === '/account/profile-keys/import-guest' && init?.method === 'POST') {
        return json({detail: {code}}, {status: code === 'banned' ? 403 : 409})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /导入游客 Key/i}))
    await userEvent.type(screen.getByLabelText(/^游客 Profile Key$/i), 'maspk_guest')
    await userEvent.click(screen.getByRole('button', {name: /^导入$/i}))

    const dialog = screen.getByRole('dialog')
    await expect(within(dialog).findByText(new RegExp(message, 'i'))).resolves.toBeInTheDocument()
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

  it('renames a profile from the profile keys list', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    let submittedBody: unknown
    mockFetch(async (input, init) => {
      if (input === '/account/profile-keys' && !init?.method) {
        return json({
          items: [
            {
              id: 9,
              user_id: 2,
              display_name: 'Main',
              profile_key: 'maspk_main',
              storage_usage: 0,
              storage_limit: 10485760,
              lock_status: 'none',
              revoked_at: null,
              last_used_at: null,
              last_upload_at: null,
              created_at: '2026-07-07T08:00:00',
              is_guest: false,
              guest_retention_days: null,
              guest_expires_at: null,
            },
          ],
        })
      }
      if (input === '/account/profiles/9' && init?.method === 'PATCH') {
        submittedBody = JSON.parse(String(init.body))
        return json({
          id: 9,
          user_id: 2,
          display_name: 'Desktop',
          profile_key: 'maspk_main',
          storage_usage: 0,
          storage_limit: 10485760,
          lock_status: 'none',
          revoked_at: null,
          last_used_at: null,
          last_upload_at: null,
          created_at: '2026-07-07T08:00:00',
          is_guest: false,
          guest_retention_days: null,
          guest_expires_at: null,
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profile-keys']}>
        <App />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', {name: /改名 Main/i}))
    expect(screen.getByDisplayValue('Main')).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText(/显示名称/i))
    await userEvent.type(screen.getByLabelText(/显示名称/i), 'Desktop')
    await userEvent.click(screen.getByRole('button', {name: /^保存$/i}))

    await expect(screen.findByText('Desktop')).resolves.toBeInTheDocument()
    expect(screen.queryByText('Main')).not.toBeInTheDocument()
    expect(submittedBody).toEqual({display_name: 'Desktop'})
    expectFetchCalled('/account/profiles/9', {method: 'PATCH'})
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
      if (typeof input === 'string' && input.startsWith('/admin/users')) {
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

  it('requests paginated admin users and resets to page one when filters change', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (typeof input === 'string' && input.startsWith('/admin/users?')) {
        return json({
          items: [
            {
              ...normalUser,
              profile_count: 1,
              storage_usage: 12,
              last_upload_at: '2026-02-05T10:00:00Z',
              last_submod_use: null,
              lock_status: 'none',
              ban_status: 'none',
            },
          ],
          page: input.includes('page=2') ? 2 : 1,
          page_size: input.includes('page_size=50') ? 50 : 25,
          has_next: !input.includes('page=2'),
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/users']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByText('Player')).resolves.toBeInTheDocument()
    expectFetchCalled('/admin/users?page=1&page_size=25&sort=id&order=asc')

    await userEvent.click(screen.getByRole('button', {name: /下一页/i}))
    await waitFor(() => expectFetchCalled('/admin/users?page=2&page_size=25&sort=id&order=asc'))

    await userEvent.selectOptions(screen.getByLabelText(/每页/i), '50')
    await waitFor(() => expectFetchCalled('/admin/users?page=1&page_size=50&sort=id&order=asc'))

    await userEvent.selectOptions(screen.getByLabelText(/排序字段/i), 'last_upload_at')
    await waitFor(() => expectFetchCalled('/admin/users?page=1&page_size=50&sort=last_upload_at&order=asc'))

    await userEvent.selectOptions(screen.getByLabelText(/排序方向/i), 'desc')
    await waitFor(() => expectFetchCalled('/admin/users?page=1&page_size=50&sort=last_upload_at&order=desc'))

    await userEvent.type(screen.getByLabelText(/上传开始/i), '2026-02-01')
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('last_upload_from=2026-02-01'),
        expect.objectContaining({credentials: 'include'}),
      )
    })

    await userEvent.type(screen.getByPlaceholderText(/搜索用户/i), 'guest')
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining('q=guest'), expect.objectContaining({credentials: 'include'}))
    })
  })

  it('disables admin user pagination buttons from page and has_next', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (typeof input === 'string' && input.startsWith('/admin/users?')) {
        return json({items: [], page: 1, page_size: 25, has_next: false})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/users']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByText(/第 1 页/i)).resolves.toBeInTheDocument()
    expect(screen.getByRole('button', {name: /上一页/i})).toBeDisabled()
    expect(screen.getByRole('button', {name: /下一页/i})).toBeDisabled()
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

  it('renames a profile from the profile detail page', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(normalUser))
    let submittedBody: unknown
    mockFetch((input, init) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/account/profiles/10' && !init?.method) {
        return json({
          profile: {
            id: 10,
            user_id: 2,
            display_name: 'Fresh profile',
            profile_key: 'maspk_empty',
            storage_usage: 0,
            storage_limit: 10485760,
            lock_status: 'none',
            revoked_at: null,
            last_used_at: null,
            last_upload_at: null,
            created_at: '2026-07-07T08:00:00',
            is_guest: false,
            guest_retention_days: null,
            guest_expires_at: null,
          },
        })
      }
      if (input === '/account/profiles/10' && init?.method === 'PATCH') {
        submittedBody = JSON.parse(String(init.body))
        return json({
          id: 10,
          user_id: 2,
          display_name: 'Laptop',
          profile_key: 'maspk_empty',
          storage_usage: 0,
          storage_limit: 10485760,
          lock_status: 'none',
          revoked_at: null,
          last_used_at: null,
          last_upload_at: null,
          created_at: '2026-07-07T08:00:00',
          is_guest: false,
          guest_retention_days: null,
          guest_expires_at: null,
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
    await userEvent.click(screen.getByRole('button', {name: /改名 Fresh profile/i}))
    await userEvent.clear(screen.getByLabelText(/显示名称/i))
    await userEvent.type(screen.getByLabelText(/显示名称/i), 'Laptop')
    await userEvent.click(screen.getByRole('button', {name: /^保存$/i}))

    await expect(screen.findByRole('heading', {level: 1, name: 'Laptop'})).resolves.toBeInTheDocument()
    expect(submittedBody).toEqual({display_name: 'Laptop'})
  })

  it('does not show profile rename controls on a guest profile detail page', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(guestUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (input === '/account/profiles/30') {
        return json({
          profile: {
            id: 30,
            user_id: 3,
            display_name: 'Guest',
            profile_key: 'maspk_guest',
            storage_usage: 0,
            storage_limit: 10485760,
            lock_status: 'none',
            revoked_at: null,
            last_used_at: '2026-07-10T08:00:00Z',
            last_upload_at: null,
            created_at: '2026-07-10T08:00:00Z',
            is_guest: true,
            guest_retention_days: 360,
            guest_expires_at: '2027-07-05T08:00:00Z',
          },
        })
      }
      if (input === '/account/profiles/30/persistent/current') {
        return json({detail: {code: 'no_current_persistent'}}, {status: 404})
      }
      if (input === '/account/profiles/30/persistent/backups') {
        return json({items: []})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/account/profiles/30']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByRole('heading', {level: 1, name: 'Guest'})).resolves.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: /改名/i})).not.toBeInTheDocument()
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
      if (typeof input === 'string' && input.startsWith('/admin/audit-logs')) {
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
          page: 1,
          page_size: 25,
          has_next: false,
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

  it('requests paginated audit logs and resets page when search or page size changes', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    mockFetch((input) => {
      if (input === '/account/profile-keys') {
        return json({items: []})
      }
      if (typeof input === 'string' && input.startsWith('/admin/audit-logs?')) {
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
          page: input.includes('page=2') ? 2 : 1,
          page_size: input.includes('page_size=50') ? 50 : 25,
          has_next: !input.includes('page=2'),
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/audit-logs']}>
        <App />
      </MemoryRouter>,
    )

    await expect(screen.findByText('admin.profile.ban')).resolves.toBeInTheDocument()
    expectFetchCalled('/admin/audit-logs?page=1&page_size=25')

    await userEvent.click(screen.getByRole('button', {name: /下一页/i}))
    await waitFor(() => expectFetchCalled('/admin/audit-logs?page=2&page_size=25'))

    await userEvent.selectOptions(screen.getByLabelText(/每页/i), '50')
    await waitFor(() => expectFetchCalled('/admin/audit-logs?page=1&page_size=50'))

    await userEvent.type(screen.getByPlaceholderText(/筛选操作或目标/i), 'ban')
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining('q=ban'), expect.objectContaining({credentials: 'include'}))
    })
  })

  it('allows admins to edit runtime system settings', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    let submittedBody: unknown
    const defaultBucket = {
      id: 1,
      name: 'Docker local storage',
      type: 'local',
      is_active: true,
      config: {path: './data/objects'},
    }
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
            guest_key_retention_days: 360,
            active_storage_bucket_id: 1,
            storage_buckets: [defaultBucket],
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
            guest_key_retention_days: 45,
            active_storage_bucket_id: 1,
            storage_buckets: [defaultBucket],
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
    const backendApiUrl = await screen.findByLabelText(/backend api url/i)
    await userEvent.clear(backendApiUrl)
    await userEvent.type(backendApiUrl, 'https://api2.example.test')
    await userEvent.clear(screen.getByLabelText(/(profile storage limit|Profile 存储上限)/i))
    await userEvent.type(screen.getByLabelText(/(profile storage limit|Profile 存储上限)/i), '20971520')
    await userEvent.clear(screen.getByLabelText(/(max active profiles|最大启用 Profile 数)/i))
    await userEvent.type(screen.getByLabelText(/(max active profiles|最大启用 Profile 数)/i), '4')
    await userEvent.clear(screen.getByLabelText(/(guest key retention|游客 Key 保留天数)/i))
    await userEvent.type(screen.getByLabelText(/(guest key retention|游客 Key 保留天数)/i), '45')
    await userEvent.click(screen.getByRole('button', {name: /(save settings|保存设置)/i}))

    await expect(screen.findByText(/(settings saved|设置已保存)/i)).resolves.toBeInTheDocument()
    expect(submittedBody).toEqual({
      backend_api_url: 'https://api2.example.test',
      frontend_web_url: 'https://portal.example.test',
      profile_storage_limit_bytes: 20971520,
      max_active_profiles_per_account: 4,
      guest_key_retention_days: 45,
      active_storage_bucket_id: 1,
      storage_buckets: [{...defaultBucket, space_budget_bytes: null}],
    })
  })

  it('allows admins to add a webdav storage bucket and mark it active', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    let submittedBody: any
    const defaultBucket = {
      id: 1,
      name: 'Docker local storage',
      type: 'local',
      is_active: true,
      config: {path: './data/objects'},
    }
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
            active_storage_bucket_id: 1,
            storage_buckets: [defaultBucket],
          },
        })
      }
      if (input === '/admin/settings' && init?.method === 'PUT') {
        submittedBody = JSON.parse(String(init.body))
        return json({
          settings: {
            backend_api_url: 'https://api.example.test',
            frontend_web_url: 'https://portal.example.test',
            profile_storage_limit_bytes: 10485760,
            max_active_profiles_per_account: 3,
            active_storage_bucket_id: 2,
            storage_buckets: [
              {...defaultBucket, is_active: false},
              {
                id: 2,
                name: 'Primary WebDAV',
                type: 'webdav',
                is_active: true,
                config: {
                  base_url: 'https://dav.example.test/root',
                  username: 'mas',
                  root_path: 'persistent',
                  has_password: true,
                },
              },
            ],
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

    await screen.findByRole('heading', {level: 1, name: /(settings|设置)/i})
    await userEvent.click(screen.getByRole('button', {name: /(add webdav bucket|添加 WebDAV 存储桶)/i}))
    await userEvent.clear(screen.getByLabelText(/(bucket name|存储桶名称)/i))
    await userEvent.type(screen.getByLabelText(/(bucket name|存储桶名称)/i), 'Primary WebDAV')
    await userEvent.type(screen.getByLabelText(/(webdav url|WebDAV URL)/i), 'https://dav.example.test/root/')
    await userEvent.type(screen.getByLabelText(/(webdav username|WebDAV 用户名)/i), 'mas')
    await userEvent.type(screen.getByLabelText(/(webdav password|WebDAV 密码)/i), 'secret')
    await userEvent.type(screen.getByLabelText(/(webdav root path|WebDAV 根路径)/i), 'persistent')
    await userEvent.click(screen.getByLabelText(/(use Primary WebDAV as active storage bucket|使用 Primary WebDAV 作为活动存储桶)/i))
    await userEvent.click(screen.getByRole('button', {name: /(save settings|保存设置)/i}))

    await expect(screen.findByText(/(settings saved|设置已保存)/i)).resolves.toBeInTheDocument()
    expect(submittedBody.storage_buckets).toEqual([
      {...defaultBucket, is_active: false, space_budget_bytes: null},
      {
        name: 'Primary WebDAV',
        type: 'webdav',
        is_active: true,
        space_budget_bytes: null,
        config: {
          base_url: 'https://dav.example.test/root/',
          username: 'mas',
          password: 'secret',
          root_path: 'persistent',
        },
      },
    ])
    expect(submittedBody.active_storage_bucket_id).toBeNull()
  })

  it('allows admins to test storage bucket read and write from settings', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    let submittedBody: any
    const defaultBucket = {
      id: 1,
      name: 'Docker local storage',
      type: 'local',
      is_active: true,
      config: {path: './data/objects'},
    }
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
            active_storage_bucket_id: 1,
            storage_buckets: [defaultBucket],
          },
        })
      }
      if (input === '/admin/storage-buckets/test' && init?.method === 'POST') {
        submittedBody = JSON.parse(String(init.body))
        return json({status: 'ok'})
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/settings']}>
        <App />
      </MemoryRouter>,
    )

    await screen.findByRole('heading', {level: 1, name: /(settings|设置)/i})
    await userEvent.click(screen.getByRole('button', {name: /(test read\/write|测试读写)/i}))

    await expect(screen.findByText(/(storage bucket read\/write test passed|存储桶读写测试通过)/i)).resolves.toBeInTheDocument()
    expect(submittedBody).toEqual({...defaultBucket, space_budget_bytes: null})
  })

  it('shows storage bucket test diagnostics when read and write test fails', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    const defaultBucket = {
      id: 1,
      name: 'Docker local storage',
      type: 'local',
      is_active: true,
      config: {path: './data/objects'},
    }
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
            active_storage_bucket_id: 1,
            storage_buckets: [defaultBucket],
          },
        })
      }
      if (input === '/admin/storage-buckets/test' && init?.method === 'POST') {
        return json(
          {detail: {code: 'storage_bucket_test_failed', phase: 'get', error_type: 'ConnectTimeout'}},
          {status: 502},
        )
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/settings']}>
        <App />
      </MemoryRouter>,
    )

    await screen.findByRole('heading', {level: 1, name: /(settings|设置)/i})
    await userEvent.click(screen.getByRole('button', {name: /(test read\/write|测试读写)/i}))

    await expect(screen.findByText(/storage_bucket_test_failed.*phase=get.*error=ConnectTimeout/i)).resolves.toBeInTheDocument()
  })

  it('shows storage bucket usage and keeps referenced connection fields locked', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    let submittedBody: any
    const webdavBucket = {
      id: 2,
      name: 'Archive WebDAV',
      type: 'webdav',
      is_active: false,
      space_budget_bytes: 2048,
      usage_summary: {
        file_count: 2,
        total_size: 12,
        backup_reference_count: 2,
        current_reference_count: 1,
      },
      is_config_locked: true,
      config: {
        base_url: 'https://dav.example.test/root',
        username: 'mas',
        root_path: 'persistent',
        has_password: true,
      },
    }
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
            active_storage_bucket_id: 1,
            storage_buckets: [
              {
                id: 1,
                name: 'Docker local storage',
                type: 'local',
                is_active: true,
                space_budget_bytes: null,
                usage_summary: {file_count: 0, total_size: 0, backup_reference_count: 0, current_reference_count: 0},
                is_config_locked: false,
                config: {path: './data/objects'},
              },
              webdavBucket,
            ],
          },
        })
      }
      if (input === '/admin/storage-buckets/2/usage') {
        return json({
          bucket_id: 2,
          file_count: 2,
          total_size: 12,
          backup_reference_count: 2,
          current_reference_count: 1,
          space_budget_bytes: 2048,
        })
      }
      if (input === '/admin/settings' && init?.method === 'PUT') {
        submittedBody = JSON.parse(String(init.body))
        return json({
          settings: {
            backend_api_url: 'https://api.example.test',
            frontend_web_url: 'https://portal.example.test',
            profile_storage_limit_bytes: 10485760,
            max_active_profiles_per_account: 3,
            active_storage_bucket_id: 1,
            storage_buckets: [{...webdavBucket, name: 'Archive Renamed', space_budget_bytes: 4096}],
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

    await screen.findByRole('heading', {level: 1, name: /(settings|设置)/i})
    expect(screen.getByLabelText(/(webdav url|WebDAV URL)/i)).toBeDisabled()
    expect(screen.getByLabelText(/(webdav username|WebDAV 用户名)/i)).toBeDisabled()
    expect(screen.getByLabelText(/(webdav password|WebDAV 密码)/i)).toBeDisabled()
    expect(screen.getByLabelText(/(webdav root path|WebDAV 根路径)/i)).toBeDisabled()
    expect(screen.getByLabelText(/(bucket name|存储桶名称)/i)).toBeEnabled()
    const budgetInput = screen.getAllByLabelText(/(space budget|可用空间预算)/i)[1]
    expect(budgetInput).toBeEnabled()

    await userEvent.click(screen.getAllByRole('button', {name: /(usage info|使用信息)/i})[1])
    await expect(screen.findByText(/(files|文件).*2/i)).resolves.toBeInTheDocument()
    expect(screen.getByText(/12 B/)).toBeInTheDocument()
    expectFetchCalled('/admin/storage-buckets/2/usage')

    await userEvent.clear(screen.getByLabelText(/(bucket name|存储桶名称)/i))
    await userEvent.type(screen.getByLabelText(/(bucket name|存储桶名称)/i), 'Archive Renamed')
    await userEvent.clear(budgetInput)
    await userEvent.type(budgetInput, '4096')
    await userEvent.click(screen.getByRole('button', {name: /(save settings|保存设置)/i}))

    await expect(screen.findByText(/(settings saved|设置已保存)/i)).resolves.toBeInTheDocument()
    expect(submittedBody.storage_buckets[1]).toMatchObject({
      id: 2,
      name: 'Archive Renamed',
      space_budget_bytes: 4096,
      config: {
        base_url: 'https://dav.example.test/root',
        username: 'mas',
        password: '',
        root_path: 'persistent',
      },
    })
  })

  it('confirms storage bucket deletion and calls the confirmed delete endpoint', async () => {
    localStorage.setItem('mas_unisync_user', JSON.stringify(adminUser))
    const defaultBucket = {
      id: 1,
      name: 'Docker local storage',
      type: 'local',
      is_active: true,
      config: {path: './data/objects'},
    }
    const archiveBucket = {
      id: 2,
      name: 'Archive WebDAV',
      type: 'webdav',
      is_active: false,
      is_config_locked: true,
      space_budget_bytes: null,
      usage_summary: {file_count: 1, total_size: 6, backup_reference_count: 1, current_reference_count: 0},
      config: {
        base_url: 'https://dav.example.test/root',
        username: 'mas',
        root_path: 'persistent',
        has_password: true,
      },
    }
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
            active_storage_bucket_id: 1,
            storage_buckets: [defaultBucket, archiveBucket],
          },
        })
      }
      if (input === '/admin/storage-buckets/2?confirm=true' && init?.method === 'DELETE') {
        return json({
          deleted_backup_count: 1,
          migrated_current_count: 0,
          removed_current_count: 0,
          deleted_version_count: 1,
        })
      }
      return json({detail: {code: 'not_found'}}, {status: 404})
    })

    render(
      <MemoryRouter initialEntries={['/admin/settings']}>
        <App />
      </MemoryRouter>,
    )

    await screen.findByText('Archive WebDAV')
    const deleteButtons = screen.getAllByRole('button', {name: /(delete bucket|删除存储桶)/i})
    await userEvent.click(deleteButtons.find((button) => !button.hasAttribute('disabled')) as HTMLElement)
    expect(screen.getByText(/(object files will not be deleted|实际对象文件不会被删除)/i)).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', {name: /^(delete bucket|删除存储桶)$/i}))

    await waitFor(() => expect(screen.queryByText('Archive WebDAV')).not.toBeInTheDocument())
    expectFetchCalled('/admin/storage-buckets/2?confirm=true', {method: 'DELETE'})
  })
})
