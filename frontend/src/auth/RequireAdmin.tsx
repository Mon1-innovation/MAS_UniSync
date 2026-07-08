import {Navigate} from 'react-router-dom'
import {useTranslation} from 'react-i18next'
import {useAuth} from './AuthProvider'
import {ErrorBanner} from '../components/ErrorBanner'
import {LoadingState} from '../components/LoadingState'

export function RequireAdmin({children}: {children: React.ReactNode}) {
  const {t} = useTranslation()
  const {user, isCheckingSession} = useAuth()

  if (isCheckingSession) {
    return <LoadingState label={t('common.checkingSession')} />
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (user.role !== 'admin') {
    return <ErrorBanner title={t('admin.accessDeniedTitle')} message={t('admin.accessDeniedMessage')} />
  }

  return <>{children}</>
}
