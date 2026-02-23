import { createContext, useContext, useState, useEffect } from 'react'
import { generateId } from '@/lib/utils'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    // Check for stored user on mount
    const storedUser = localStorage.getItem('rag_user')
    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser))
      } catch (e) {
        localStorage.removeItem('rag_user')
      }
    }
    setIsLoading(false)
  }, [])

  const login = async (userData) => {
    // userData comes from the API response (already has id, etc.)
    const user = {
      ...userData,
      createdAt: userData.created_at || new Date().toISOString(),
    }

    setUser(user)
    localStorage.setItem('rag_user', JSON.stringify(user))
    return user
  }

  const logout = () => {
    setUser(null)
    localStorage.removeItem('rag_user')
    localStorage.removeItem('rag_thread_id')
    localStorage.removeItem('rag_messages')
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
