import {Button, Box, Text, Avatar} from '@primer/react'
import {SignOutIcon} from '@primer/octicons-react'
import {useAuth} from '../auth/AuthProvider'

export function Header() {
  const {user, logout} = useAuth()
  const name = user?.display_name || user?.username || 'Guest'

  return (
    <header className="app-header">
      <Box className="app-header-inner">
        <Text as="strong" className="brand">
          MAS UniSync
        </Text>
        {user ? (
          <Box sx={{display: 'flex', alignItems: 'center', gap: 2}}>
            <Avatar src={user.avatar_url || ''} alt={name} size={24} />
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
