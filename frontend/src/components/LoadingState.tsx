import {Box, Spinner, Text} from '@primer/react'

export function LoadingState({label = 'Loading'}: {label?: string}) {
  return (
    <Box className="loading-state">
      <Spinner size="small" />
      <Text>{label}</Text>
    </Box>
  )
}
