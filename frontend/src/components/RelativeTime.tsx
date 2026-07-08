import {useTranslation} from 'react-i18next'

export function RelativeTime({value, fallback}: {value: string | null | undefined; fallback?: string}) {
  const {t} = useTranslation()
  if (!value) {
    return <span className="muted">{fallback || t('common.never')}</span>
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return <span>{value}</span>
  }

  return <time dateTime={value}>{date.toLocaleString()}</time>
}
