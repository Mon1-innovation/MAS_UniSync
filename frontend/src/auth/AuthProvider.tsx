import {createContext, useCallback, useContext, useEffect, useMemo, useState} from 'react'
import {useNavigate} from 'react-router-dom'
import {ApiError} from '../api/client'
import {loginFlarum, loginGuest as loginGuestRequest, logout as logoutRequest} from '../api/authApi'
import {listProfileKeys} from '../api/profileKeysApi'
import type {User} from '../api/types'
import {clearStoredUser, readStoredUser, storeUser} from './storage'

interface AuthContextValue {
  user: User | null
  isCheckingSession: boolean
  login: (identification: string, password: string) => Promise<User>
  loginGuest: (profileKey: string) => Promise<User>
  logout: () => Promise<void>
  setUser: (user: User | null) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({children}: {children: React.ReactNode}) {
  const [user, setUserState] = useState<User | null>(() => readStoredUser())
  const [isCheckingSession, setIsCheckingSession] = useState(() => readStoredUser() !== null)
  const navigate = useNavigate()

  const setUser = useCallback((nextUser: User | null) => {
    setUserState(nextUser)
    if (nextUser) {
      storeUser(nextUser)
    } else {
      clearStoredUser()
    }
  }, [])

  useEffect(() => {
    if (!user) {
      setIsCheckingSession(false)
      return
    }

    let cancelled = false
    listProfileKeys()
      .then(() => {
        if (!cancelled) {
          setIsCheckingSession(false)
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return
        }
        setIsCheckingSession(false)
        if (error instanceof ApiError && error.status === 401) {
          setUser(null)
          navigate('/login', {replace: true})
        }
      })

    return () => {
      cancelled = true
    }
  }, [navigate, setUser, user])

  const login = useCallback(
    async (identification: string, password: string) => {
      const response = await loginFlarum(identification, password)
      setUser(response.user)
      navigate(response.user.role === 'admin' ? '/admin/users' : '/account/profile-keys', {replace: true})
      return response.user
    },
    [navigate, setUser],
  )

  const loginGuest = useCallback(
    async (profileKey: string) => {
      const response = await loginGuestRequest(profileKey)
      setUser(response.user)
      navigate('/account/profile-keys', {replace: true})
      return response.user
    },
    [navigate, setUser],
  )

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      setUser(null)
      navigate('/login', {replace: true})
    }
  }, [navigate, setUser])

  const value = useMemo(
    () => ({user, isCheckingSession, login, loginGuest, logout, setUser}),
    [isCheckingSession, login, loginGuest, logout, setUser, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
