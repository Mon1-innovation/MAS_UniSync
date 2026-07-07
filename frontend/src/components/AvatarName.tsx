import {Avatar, Box, Text} from '@primer/react'
import type {User} from '../api/types'

export function AvatarName({user, subtitle}: {user: Pick<User, 'avatar_url' | 'display_name' | 'username'>; subtitle?: string}) {
  const name = user.display_name || user.username
  const initial = name.trim().charAt(0).toUpperCase() || 'U'
  return (
    <Box sx={{display: 'flex', alignItems: 'center', gap: 2, minWidth: 0}}>
      {user.avatar_url ? (
        <Avatar src={user.avatar_url} alt={name} size={32} />
      ) : (
        <span className="avatar-fallback" aria-label={name}>
          {initial}
        </span>
      )}
      <Box sx={{minWidth: 0}}>
        <Text sx={{display: 'block', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
          {name}
        </Text>
        <Text sx={{display: 'block', color: 'fg.muted', fontSize: 0}}>{subtitle || `@${user.username}`}</Text>
      </Box>
    </Box>
  )
}
