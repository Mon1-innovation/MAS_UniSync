import {Box, Text} from '@primer/react'
import {ByteSize} from './ByteSize'

export function StorageUsageBar({usage, limit}: {usage: number; limit: number}) {
  const safeUsage = Math.max(0, usage || 0)
  const safeLimit = Math.max(0, limit || 0)
  const percent = safeLimit > 0 ? Math.min(100, Math.round((safeUsage / safeLimit) * 100)) : 0

  return (
    <Box className="storage-meter">
      <Box className="storage-meter-header">
        <Text as="span">Storage usage</Text>
        <strong>
          <ByteSize value={safeUsage} /> / <ByteSize value={safeLimit} />
        </strong>
      </Box>
      <Box
        className="storage-meter-track"
        role="progressbar"
        aria-label="Storage usage"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <Box className="storage-meter-fill" style={{width: `${percent}%`}} />
      </Box>
    </Box>
  )
}
