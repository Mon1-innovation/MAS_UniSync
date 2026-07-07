import {Button, Box, Text} from '@primer/react'
import {CopyIcon} from '@primer/octicons-react'
import {useState} from 'react'

export function CopyableSecret({value}: {value: string}) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard?.writeText(value)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Box className="copyable-secret">
      <Text as="code">{value}</Text>
      <Button type="button" size="small" leadingVisual={CopyIcon} aria-label="Copy profile key" onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </Box>
  )
}
