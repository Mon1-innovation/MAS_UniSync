import {expect, test} from '@playwright/test'

const normalUser = {
  id: 2,
  flarum_user_id: 20,
  username: 'player',
  display_name: 'Player',
  avatar_url: null,
  role: 'user',
  last_login_at: '2026-07-07T08:00:00',
}

const adminUser = {
  id: 1,
  flarum_user_id: 10,
  username: 'admin',
  display_name: 'Admin User',
  avatar_url: null,
  role: 'admin',
  last_login_at: '2026-07-07T08:00:00',
}

test.beforeEach(async ({page, context}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()

    if (path === '/login/flarum' && method === 'POST') {
      const body = route.request().postDataJSON() as {identification?: string}
      await route.fulfill({json: {user: body.identification === 'admin' ? adminUser : normalUser}})
      return
    }

    if (path === '/logout' && method === 'POST') {
      await route.fulfill({status: 204, body: ''})
      return
    }

    if (path === '/account/profile-keys' && method === 'GET') {
      await route.fulfill({json: {items: []}})
      return
    }

    if (path === '/account/profile-keys' && method === 'POST') {
      await route.fulfill({
        status: 201,
        json: {
          id: 11,
          user_id: 2,
          display_name: 'Smoke key',
          profile_key: 'maspk_smoke',
          revoked_at: null,
          last_used_at: null,
          last_upload_at: null,
          created_at: '2026-07-07T08:00:00',
        },
      })
      return
    }

    if (path === '/admin/users') {
      await route.fulfill({
        json: {
          items: [
            {
              ...adminUser,
              profile_count: 1,
              storage_usage: 2048,
              last_upload_at: '2026-07-07T08:00:00',
              last_submod_use: '2026-07-07T08:00:00',
              lock_status: 'none',
              ban_status: 'none',
            },
          ],
        },
      })
      return
    }

    if (path === '/admin/audit-logs') {
      await route.fulfill({
        json: {
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
              user_agent: 'playwright',
              created_at: '2026-07-07T08:00:00',
            },
          ],
        },
      })
      return
    }

    if (path === '/admin/profiles/42') {
      await route.fulfill({
        json: {
          profile: {
            id: 42,
            user_id: 2,
            display_name: 'Admin profile',
            profile_key: 'maspk_admin',
            revoked_at: null,
            last_used_at: null,
            last_upload_at: null,
            created_at: '2026-07-07T08:00:00',
          },
        },
      })
      return
    }

    await route.fallback()
  })
})

test('normal user can sign in, create, and copy a profile key', async ({page}) => {
  await page.goto('/')
  await page.getByLabel(/flarum account/i).fill('player')
  await page.getByLabel(/password/i).fill('secret')
  await page.getByRole('button', {name: /sign in/i}).click()

  await expect(page.getByRole('heading', {level: 1, name: /profile keys/i})).toBeVisible()
  await page.getByRole('button', {name: /new profile key/i}).click()
  await page.getByLabel(/display name/i).fill('Smoke key')
  await page.getByRole('button', {name: /create key/i}).click()
  await expect(page.getByText('maspk_smoke')).toBeVisible()

  await page.getByRole('button', {name: /copy profile key/i}).click()
  await expect(page.locator('.copyable-secret button').filter({hasText: 'Copied'})).toBeVisible()
})

test('admin can view users, audit logs, and open a dangerous action dialog', async ({page}) => {
  await page.goto('/')
  await page.getByLabel(/flarum account/i).fill('admin')
  await page.getByLabel(/password/i).fill('secret')
  await page.getByRole('button', {name: /sign in/i}).click()

  await expect(page.getByRole('heading', {name: /admin users/i})).toBeVisible()
  await page.getByRole('link', {name: /audit logs/i}).click()
  await expect(page.getByRole('link', {name: '#42'})).toBeVisible()
  await page.getByRole('link', {name: '#42'}).click()
  await expect(page.getByRole('heading', {name: /admin profile/i})).toBeVisible()

  await page.getByRole('button', {name: 'Ban profile', exact: true}).click()
  await expect(page.getByRole('dialog', {name: /ban this profile/i})).toBeVisible()
})
