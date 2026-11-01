import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const ThemeContext = createContext(null)
const TOKENS = ['bg', 'panel', 'panel2', 'line', 'fg', 'muted', 'ink', 'late', 'absent', 'spoof', 'glow1', 'glow2', 'glow3']

function readColors() {
  const style = getComputedStyle(document.documentElement)
  return Object.fromEntries(
    TOKENS.map((t) => {
      const rgb = style.getPropertyValue(`--${t}`).trim().split(/\s+/).join(',')
      return [t, `rgb(${rgb})`]
    }),
  )
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() =>
    document.documentElement.classList.contains('dark') ? 'dark' : 'light',
  )
  const [colors, setColors] = useState(readColors)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#060814' : '#F5F4FF')
    try {
      localStorage.setItem('sfa_theme', theme)
    } catch {
      /* ignore */
    }
    setColors(readColors())
  }, [theme])

  const toggle = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), [])
  const value = useMemo(() => ({ theme, toggle, colors }), [theme, toggle, colors])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
