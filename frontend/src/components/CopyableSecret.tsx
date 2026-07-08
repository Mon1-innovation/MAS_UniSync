import {Button, Box, Text} from '@primer/react'
import {CopyIcon} from '@primer/octicons-react'
import {useState} from 'react'

export function CopyableSecret({value}: {value: string}) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    const didCopy = await writeTextToClipboard(value)
    if (!didCopy) {
      return
    }

    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Box className={`copyable-secret ${copied ? 'is-copied' : ''}`}>
      <Text as="code">{value}</Text>
      <Button type="button" size="small" leadingVisual={CopyIcon} aria-label="Copy profile key" onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </Box>
  )
}

async function writeTextToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return true
    } catch {
      // Fall through to the legacy path for browsers or deployments where the
      // async Clipboard API exists but is blocked by the current context.
    }
  }

  return copyWithSelection(value)
}

function copyWithSelection(value: string) {
  if (typeof document.execCommand !== 'function') {
    return false
  }

  const activeElement = document.activeElement
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.readOnly = true
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.width = '1px'
  textarea.style.height = '1px'
  textarea.style.opacity = '0'

  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)

  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
    if (activeElement instanceof HTMLElement) {
      activeElement.focus()
    }
  }
}
