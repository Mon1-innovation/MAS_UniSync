import {Box, UnderlineNav} from '@primer/react'
import {KeyIcon, ShieldLockIcon} from '@primer/octicons-react'
import {Link, useLocation} from 'react-router-dom'
import {useAuth} from '../auth/AuthProvider'

export function SideNav() {
  const location = useLocation()
  const {user} = useAuth()
  const selected = location.pathname.startsWith('/admin') ? 'admin' : 'profile'

  return (
    <Box className="repo-tabs">
      <UnderlineNav aria-label="Primary">
        <UnderlineNav.Item as={Link} to="/account/profile-keys" icon={KeyIcon} aria-current={selected === 'profile' ? 'page' : undefined}>
          Profile keys
        </UnderlineNav.Item>
        {user?.role === 'admin' ? (
          <UnderlineNav.Item as={Link} to="/admin/users" icon={ShieldLockIcon} aria-current={selected === 'admin' ? 'page' : undefined}>
            Admin
          </UnderlineNav.Item>
        ) : null}
      </UnderlineNav>
    </Box>
  )
}
