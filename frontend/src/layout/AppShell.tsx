import {Box} from '@primer/react'
import {Header} from './Header'
import {SideNav} from './SideNav'

export function AppShell({children}: {children: React.ReactNode}) {
  return (
    <>
      <Header />
      <SideNav />
      <Box as="main" className="page-container">
        {children}
      </Box>
    </>
  )
}
