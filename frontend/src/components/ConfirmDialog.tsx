import {Button, Box, Text} from '@primer/react'
import {useTranslation} from 'react-i18next'

interface ConfirmDialogProps {
  title: string
  message: string
  confirmText: string
  variant?: 'danger' | 'primary'
  onConfirm: () => void | Promise<void>
  onCancel: () => void
  isBusy?: boolean
}

export function ConfirmDialog({title, message, confirmText, variant = 'danger', onConfirm, onCancel, isBusy}: ConfirmDialogProps) {
  const {t} = useTranslation()
  return (
    <Box className="dialog-backdrop" role="presentation">
      <Box className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title">
        <Text as="h2" id="confirm-dialog-title" sx={{fontSize: 3, m: 0}}>
          {title}
        </Text>
        <Text as="p" sx={{color: 'fg.muted', my: 3}}>
          {message}
        </Text>
        <Box sx={{display: 'flex', justifyContent: 'flex-end', gap: 2}}>
          <Button type="button" onClick={onCancel} disabled={isBusy}>
            {t('common.cancel')}
          </Button>
          <Button type="button" variant={variant} onClick={onConfirm} disabled={isBusy}>
            {confirmText}
          </Button>
        </Box>
      </Box>
    </Box>
  )
}
