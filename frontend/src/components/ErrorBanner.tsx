import {Flash} from '@primer/react'

export function ErrorBanner({title = 'Something went wrong', message}: {title?: string; message: string}) {
  return (
    <Flash variant="danger">
      <strong>{title}.</strong> {message}
    </Flash>
  )
}
