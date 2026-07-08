import {Label} from '@primer/react'
import {useTranslation} from 'react-i18next'

type Status = 'active' | 'none' | 'admin' | 'user' | 'revoked' | string | null | undefined

export function StatusLabel({status}: {status: Status}) {
  const {t} = useTranslation()
  const normalized = status || 'none'
  const variant = normalized === 'active' || normalized === 'admin' ? 'success' : normalized === 'revoked' ? 'danger' : 'secondary'
  return <Label variant={variant}>{t(`status.${normalized}`, {defaultValue: normalized})}</Label>
}
