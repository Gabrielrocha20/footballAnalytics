import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { api, getToken, setToken, onUnauthorized } from '../lib/api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [status, setStatus] = useState('checking') // checking | anonymous | authenticated | unconfigured
  const [error, setError] = useState(null)

  const bootstrap = useCallback(async () => {
    setStatus('checking')
    setError(null)
    try {
      const info = await api.authStatus()
      if (!info.configured) {
        setStatus('unconfigured')
        return
      }
      const token = getToken()
      if (!token) {
        setStatus('anonymous')
        return
      }
      try {
        await api.authMe()
        setStatus('authenticated')
      } catch {
        setToken('')
        setStatus('anonymous')
      }
    } catch (err) {
      setError(err)
      setStatus('anonymous')
    }
  }, [])

  useEffect(() => {
    onUnauthorized(() => {
      setToken('')
      setStatus('anonymous')
    })
    bootstrap()
  }, [bootstrap])

  const login = useCallback(async (rawToken) => {
    const token = rawToken.trim()
    setToken(token)
    try {
      await api.authMe()
      setStatus('authenticated')
      return { ok: true }
    } catch (err) {
      setToken('')
      return { ok: false, message: err.status === 401 ? 'Token inválido ou expirado.' : err.message }
    }
  }, [])

  const logout = useCallback(async () => {
    setToken('')
    setStatus('anonymous')
    api.logout().catch(() => {})
  }, [])

  return (
    <AuthContext.Provider value={{ status, error, login, logout, retry: bootstrap }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth deve ser usado dentro de AuthProvider')
  return ctx
}
