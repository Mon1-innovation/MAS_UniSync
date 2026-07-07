import {BaseStyles, ThemeProvider} from '@primer/react'
import {Link, Navigate, Route, Routes} from 'react-router-dom'
import {AuthProvider} from './auth/AuthProvider'
import {RequireAdmin} from './auth/RequireAdmin'
import {RequireAuth} from './auth/RequireAuth'
import {AppShell} from './layout/AppShell'
import {LoginPage} from './pages/LoginPage'
import {ProfileKeysPage} from './pages/ProfileKeysPage'
import {AdminAuditLogsPage} from './pages/admin/AdminAuditLogsPage'
import {AdminProfileDetailPage} from './pages/admin/AdminProfileDetailPage'
import {AdminUserDetailPage} from './pages/admin/AdminUserDetailPage'
import {AdminUsersPage} from './pages/admin/AdminUsersPage'
import './styles/github.css'

export function App() {
  return (
    <ThemeProvider colorMode="light">
      <BaseStyles>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<Navigate to="/account/profile-keys" replace />} />
            <Route
              path="/account/profile-keys"
              element={
                <RequireAuth>
                  <AppShell>
                    <ProfileKeysPage />
                  </AppShell>
                </RequireAuth>
              }
            />
            <Route
              path="/admin/users"
              element={
                <RequireAdmin>
                  <AppShell>
                    <AdminNav />
                    <AdminUsersPage />
                  </AppShell>
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/users/:userId"
              element={
                <RequireAdmin>
                  <AppShell>
                    <AdminNav />
                    <AdminUserDetailPage />
                  </AppShell>
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/profiles/:profileId"
              element={
                <RequireAdmin>
                  <AppShell>
                    <AdminNav />
                    <AdminProfileDetailPage />
                  </AppShell>
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/audit-logs"
              element={
                <RequireAdmin>
                  <AppShell>
                    <AdminNav />
                    <AdminAuditLogsPage />
                  </AppShell>
                </RequireAdmin>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BaseStyles>
    </ThemeProvider>
  )
}

function AdminNav() {
  return (
    <nav className="subnav" aria-label="Admin">
      <Link to="/admin/users">Users</Link>
      <Link to="/admin/audit-logs">Audit logs</Link>
    </nav>
  )
}
