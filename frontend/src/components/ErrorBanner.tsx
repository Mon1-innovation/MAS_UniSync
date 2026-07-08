import {Flash} from '@primer/react'
import {useTranslation} from 'react-i18next'

export function ErrorBanner({title, message}: {title?: string; message: string}) {
  const {t} = useTranslation()
  return (
    <Flash variant="danger">
      <strong>{title || t('common.somethingWentWrong')}.</strong> {message}
    </Flash>
  )
}
