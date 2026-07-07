import {Label} from '@primer/react'

type Status = 'active' | 'none' | 'admin' | 'user' | 'revoked' | string | null | undefined

export function StatusLabel({status}: {status: Status}) {
  const normalized = status || 'none'
  const variant = normalized === 'active' || normalized === 'admin' ? 'success' : normalized === 'revoked' ? 'danger' : 'secondary'
  return <Label variant={variant}>{normalized}</Label>
}
