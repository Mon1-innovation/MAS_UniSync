export function RelativeTime({value, fallback = 'Never'}: {value: string | null | undefined; fallback?: string}) {
  if (!value) {
    return <span className="muted">{fallback}</span>
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return <span>{value}</span>
  }

  return <time dateTime={value}>{date.toLocaleString()}</time>
}
