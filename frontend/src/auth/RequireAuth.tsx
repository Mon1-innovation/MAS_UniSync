import {Navigate, useLocation} from 'react-router-dom'
import {useAuth} from './AuthProvider'
import {LoadingState} from '../components/LoadingState'

export function RequireAuth({children}: {children: React.ReactNode}) {
  const {user, isCheckingSession} = useAuth()
  const location = useLocation()

  if (isCheckingSession) {
    return <LoadingState label="Checking session" />
  }

  if (!user) {
    return <Navigate to="/login" state={{from: location}} replace />
  }

  return <>{children}</>
}
