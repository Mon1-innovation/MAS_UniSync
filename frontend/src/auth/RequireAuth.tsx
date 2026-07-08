import {Navigate, useLocation} from 'react-router-dom'
import {useTranslation} from 'react-i18next'
import {useAuth} from './AuthProvider'
import {LoadingState} from '../components/LoadingState'

export function RequireAuth({children}: {children: React.ReactNode}) {
  const {t} = useTranslation()
  const {user, isCheckingSession} = useAuth()
  const location = useLocation()

  if (isCheckingSession) {
    return <LoadingState label={t('common.checkingSession')} />
  }

  if (!user) {
    return <Navigate to="/login" state={{from: location}} replace />
  }

  return <>{children}</>
}
