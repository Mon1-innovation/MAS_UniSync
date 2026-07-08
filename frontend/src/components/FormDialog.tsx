import {Box, Button, Text} from '@primer/react'
import {useTranslation} from 'react-i18next'

export function FormDialog({
  title,
  children,
  submitText,
  onCancel,
  isBusy,
}: {
  title: string
  children: React.ReactNode
  submitText: string
  onCancel: () => void
  isBusy?: boolean
}) {
  const {t} = useTranslation()
  return (
    <Box className="dialog-backdrop" role="presentation">
      <Box className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="form-dialog-title">
        <Text as="h2" id="form-dialog-title" sx={{fontSize: 3, m: 0}}>
          {title}
        </Text>
        {children}
        <Box sx={{display: 'flex', justifyContent: 'flex-end', gap: 2, mt: 3}}>
          <Button type="button" onClick={onCancel} disabled={isBusy}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" variant="primary" disabled={isBusy}>
            {submitText}
          </Button>
        </Box>
      </Box>
    </Box>
  )
}
