import {Navigate} from 'react-router-dom'
import {useAuth} from './AuthProvider'
import {ErrorBanner} from '../components/ErrorBanner'
import {LoadingState} from '../components/LoadingState'

export function RequireAdmin({children}: {children: React.ReactNode}) {
  const {user, isCheckingSession} = useAuth()

  if (isCheckingSession) {
    return <LoadingState label="Checking session" />
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (user.role !== 'admin') {
    return <ErrorBanner title="Access denied" message="Your account does not have access to the admin area." />
  }

  return <>{children}</>
}
