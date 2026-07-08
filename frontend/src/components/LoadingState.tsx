import {Box, Spinner, Text} from '@primer/react'
import {useTranslation} from 'react-i18next'

export function LoadingState({label}: {label?: string}) {
  const {t} = useTranslation()
  return (
    <Box className="loading-state">
      <Spinner size="small" />
      <Text>{label || t('common.loading')}</Text>
    </Box>
  )
}
