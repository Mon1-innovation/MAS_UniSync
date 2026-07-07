export function ByteSize({value}: {value: number | null | undefined}) {
  const bytes = value || 0
  const units = ['B', 'KB', 'MB', 'GB']
  let amount = bytes
  let unit = units[0]
  for (let index = 0; index < units.length - 1 && amount >= 1024; index += 1) {
    amount /= 1024
    unit = units[index + 1]
  }
  return <span>{`${amount >= 10 || unit === 'B' ? amount.toFixed(0) : amount.toFixed(1)} ${unit}`}</span>
}
