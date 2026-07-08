import {render, screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach, describe, expect, it, vi} from 'vitest'
import {CopyableSecret} from './CopyableSecret'

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
const originalExecCommand = Object.getOwnPropertyDescriptor(document, 'execCommand')

describe('CopyableSecret', () => {
  afterEach(() => {
    vi.restoreAllMocks()

    if (originalClipboard) {
      Object.defineProperty(navigator, 'clipboard', originalClipboard)
    } else {
      Reflect.deleteProperty(navigator, 'clipboard')
    }

    if (originalExecCommand) {
      Object.defineProperty(document, 'execCommand', originalExecCommand)
    } else {
      Reflect.deleteProperty(document, 'execCommand')
    }
  })

  it('falls back to document copy when the Clipboard API is unavailable', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    })

    const copiedValues: string[] = []
    const execCommand = vi.fn((command: string) => {
      const activeElement = document.activeElement
      if (command === 'copy' && activeElement instanceof HTMLTextAreaElement) {
        copiedValues.push(activeElement.value)
        return true
      }
      return false
    })
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    })

    render(<CopyableSecret value="maspk_unit" />)

    await userEvent.click(screen.getByRole('button', {name: /复制 profile key/i}))

    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(copiedValues).toEqual(['maspk_unit'])
    expect(screen.getByText('已复制')).toBeInTheDocument()
  })
})
