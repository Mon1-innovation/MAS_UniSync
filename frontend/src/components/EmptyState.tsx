import {Box, Text} from '@primer/react'

export function EmptyState({title, message}: {title: string; message: string}) {
  return (
    <Box className="empty-state">
      <Text as="h2" sx={{fontSize: 3, m: 0}}>
        {title}
      </Text>
      <Text as="p" sx={{color: 'fg.muted', mb: 0}}>
        {message}
      </Text>
    </Box>
  )
}
