import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { authApi } from "@/api/resources"
import { setAccessToken } from "@/api/client"
import type { User } from "@/api/types"

type AuthContextValue = {
  user: User | null
  ready: boolean
  setSession: (accessToken: string, user: User) => void
  clearSession: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  const setSession = (token: string, nextUser: User) => {
    setAccessToken(token)
    setUser(nextUser)
  }

  const clearSession = () => {
    setAccessToken(null)
    setUser(null)
  }

  useEffect(() => {
    const bootstrap = async () => {
      try {
        const tokens = await authApi.refresh()
        setSession(tokens.accessToken, tokens.user)
      } catch {
        clearSession()
      } finally {
        setReady(true)
      }
    }
    void bootstrap()
  }, [])

  const value = useMemo(() => ({ user, ready, setSession, clearSession }), [user, ready])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
