import {Button, Box, Text, Avatar} from '@primer/react'
import {DatabaseIcon, SignOutIcon} from '@primer/octicons-react'
import {useAuth} from '../auth/AuthProvider'

export function Header() {
  const {user, logout} = useAuth()
  const name = user?.display_name || user?.username || 'Guest'
  const initial = name.trim().charAt(0).toUpperCase() || 'U'

  return (
    <header className="app-header">
      <Box className="app-header-inner">
        <Box className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            <DatabaseIcon size={18} />
          </span>
          <Text as="strong" className="brand">
            MAS UniSync
          </Text>
        </Box>
        {user ? (
          <Box className="header-user">
            {user.avatar_url ? (
              <Avatar src={user.avatar_url} alt={name} size={24} />
            ) : (
              <span className="avatar-fallback avatar-fallback-sm" aria-label={name}>
                {initial}
              </span>
            )}
            <Text sx={{fontSize: 1, color: 'canvas.default'}}>{user.username}</Text>
            <Button type="button" size="small" leadingVisual={SignOutIcon} onClick={logout}>
              Sign out
            </Button>
          </Box>
        ) : null}
      </Box>
    </header>
  )
}
