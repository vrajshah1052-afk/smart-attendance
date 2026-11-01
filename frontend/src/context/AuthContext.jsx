import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, getToken, setToken } from '../api/client'

const AuthContext = createContext(null)
const USER_KEY = 'sfa_user'

function readUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw && getToken() ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(readUser)

  const persist = useCallback((next) => {
    setUser(next)
    try {
      if (next) localStorage.setItem(USER_KEY, JSON.stringify(next))
      else localStorage.removeItem(USER_KEY)
    } catch {
      /* ignore storage failures */
    }
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    persist(null)
  }, [persist])

  // sign in with a token response ({ access_token, user }) from login or a self sign-up
  const adopt = useCallback(
    (res) => {
      setToken(res.access_token)
      persist(res.user)
      return res.user
    },
    [persist],
  )

  const login = useCallback(
    async (username, password) => {
      const form = new URLSearchParams({ username, password })
      return adopt(await api.form('/auth/login', form))
    },
    [adopt],
  )

  const refresh = useCallback(async () => {
    if (!getToken()) return null
    const me = await api.get('/auth/me')
    persist({ ...me })
    return me
  }, [persist])

  useEffect(() => {
    const onUnauthorized = () => logout()
    window.addEventListener('sfa:unauthorized', onUnauthorized)
    return () => window.removeEventListener('sfa:unauthorized', onUnauthorized)
  }, [logout])

  useEffect(() => {
    refresh().catch(() => {})
  }, [refresh])

  const value = useMemo(
    () => ({
      user,
      login,
      adopt,
      logout,
      refresh,
      isStaff: user?.role === 'ADMIN' || user?.role === 'TEACHER',
      isAdmin: user?.role === 'ADMIN',
    }),
    [user, login, adopt, logout, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
