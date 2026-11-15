import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  BarChart3, BookOpen, CalendarClock, ClipboardCheck, FileSpreadsheet, GitPullRequestArrow, Home, KeyRound, LogOut, Menu,
  Moon, QrCode, Radio, ScanFace, Settings2, Sun, Timer, Upload, UserCheck, UserPlus, Users, X, ListChecks,
} from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import { Aurora } from './Aurora'
import { NotificationBell } from './NotificationBell'

const STAFF_NAV = [
  {
    section: 'Class',
    items: [
      { to: '/', label: 'Today', icon: Home, end: true },
      { to: '/attendance/group', label: 'Take attendance', icon: ScanFace },
      { to: '/attendance/late', label: 'Late entry', icon: Timer },
      { to: '/live', label: 'Live recognition', icon: Radio },
      { to: '/sessions', label: 'Sessions', icon: CalendarClock },
      { to: '/courses', label: 'Courses and class codes', icon: BookOpen },
    ],
  },
  {
    section: 'Students',
    items: [
      { to: '/students', label: 'All students', icon: Users, end: true },
      { to: '/students/register', label: 'Register a student', icon: UserPlus },
      { to: '/students/import', label: 'Import from CSV', icon: Upload },
    ],
  },
  {
    section: 'Follow-up',
    items: [
      { to: '/review', label: 'Review matches', icon: ListChecks },
      { to: '/overrides', label: 'Corrections', icon: GitPullRequestArrow },
    ],
  },
  {
    section: 'Reports',
    items: [
      { to: '/reports', label: 'Registers and exports', icon: FileSpreadsheet },
      { to: '/analytics', label: 'Analytics', icon: BarChart3 },
    ],
  },
]

const STUDENT_NAV = [
  {
    section: 'Me',
    items: [
      { to: '/me', label: 'My attendance', icon: ClipboardCheck },
      { to: '/join', label: 'Join a class', icon: UserPlus },
      { to: '/qr', label: 'Mark with attendance code', icon: QrCode },
      { to: '/overrides', label: 'Correction requests', icon: GitPullRequestArrow },
    ],
  },
]

function NavList({ groups, onNavigate }) {
  return (
    <nav className="flex flex-col gap-6 px-3 py-2" aria-label="Main">
      {groups.map((g) => (
        <div key={g.section}>
          <p className="eyebrow px-3 pb-2">{g.section}</p>
          <ul className="flex flex-col gap-1">
            {g.items.map(({ to, label, icon: Icon, end, badge }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-all duration-200 ${
                      isActive
                        ? 'bg-gradient-to-r from-ink/20 via-glow1/10 to-transparent font-semibold text-fg shadow-[inset_0_0_0_1px_rgb(var(--ink)/0.25)]'
                        : 'text-muted hover:bg-panel2/70 hover:text-fg'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className="absolute -left-3 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-glow2 via-ink to-glow3 shadow-[0_0_12px_rgb(var(--ink))]" />
                      )}
                      <Icon
                        size={18}
                        strokeWidth={1.9}
                        className={isActive ? 'text-ink drop-shadow-[0_0_6px_rgb(var(--ink)/0.8)]' : 'transition-colors group-hover:text-ink'}
                      />
                      {label}
                      {badge > 0 && (
                        <span
                          className="ml-auto min-w-[22px] rounded-full bg-late/20 px-1.5 py-0.5 text-center text-xs font-bold text-late"
                          title={`${badge} waiting for approval`}
                        >
                          {badge > 99 ? '99+' : badge}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

/** How many self sign-ups are waiting for an admin. 0 for everyone else. */
function usePendingApprovals(isAdmin, pathname) {
  const [count, setCount] = useState(0)
  useEffect(() => {
    if (!isAdmin) {
      setCount(0)
      return undefined
    }
    let alive = true
    const load = () =>
      api
        .get('/students/pending')
        .then((d) => alive && setCount(d.total ?? d.items?.length ?? 0))
        .catch(() => {})
    load()
    // Admin.jsx fires this after an approve or a reject so the badge keeps up
    window.addEventListener('sfa:approvals-changed', load)
    return () => {
      alive = false
      window.removeEventListener('sfa:approvals-changed', load)
    }
  }, [isAdmin, pathname])
  return count
}

function currentLabel(groups, pathname) {
  const items = groups.flatMap((g) => g.items)
  const exact = items.find((i) => i.to === pathname)
  if (exact) return exact.label
  const prefix = items.filter((i) => i.to !== '/' && pathname.startsWith(i.to)).sort((a, b) => b.to.length - a.to.length)[0]
  return prefix?.label || (pathname === '/account' ? 'Account' : '')
}

export function Layout() {
  const { user, logout, isStaff, isAdmin } = useAuth()
  const { theme, toggle } = useTheme()
  const [drawer, setDrawer] = useState(false)
  const [menu, setMenu] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    setDrawer(false)
    setMenu(false)
  }, [location.pathname])

  const pendingApprovals = usePendingApprovals(isAdmin, location.pathname)

  const groups = isStaff
    ? [
        ...STAFF_NAV,
        ...(isAdmin
          ? [{
              section: 'Admin',
              items: [
                { to: '/approvals', label: 'Student approvals', icon: UserCheck, badge: pendingApprovals },
                { to: '/admin', label: 'System and audit', icon: Settings2 },
              ],
            }]
          : []),
      ]
    : STUDENT_NAV

  const brand = (
    <Link to="/" className="flex items-center gap-3 px-5 py-5">
      <span className="relative">
        <span className="absolute inset-0 rounded-[10px] bg-glow1 opacity-60 blur-md" aria-hidden="true" />
        <img src="/favicon.svg" alt="" width="36" height="36" className="relative" />
      </span>
      <span className="leading-tight">
        <span className="block font-display text-[15px] font-bold tracking-tight">
          Smart <span className="text-aurora">Attendance</span>
        </span>
        <span className="block text-xs text-muted">Face recognition · VIT Pune</span>
      </span>
    </Link>
  )

  const footer = (
    <div className="mx-3 mb-4 mt-auto rounded-2xl border border-line/60 bg-panel2/40 p-3.5 text-xs text-muted">
      <p className="flex items-center gap-2 font-semibold text-fg">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-glow2" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-glow2" />
        </span>
        Secure by design
      </p>
      <p className="mt-1 leading-relaxed">Face templates are AES-encrypted. Photos are never stored.</p>
    </div>
  )

  const pageLabel = currentLabel(groups, location.pathname)

  return (
    <div className="relative min-h-screen lg:grid lg:grid-cols-[272px_1fr]">
      <Aurora />
      <aside className="glass sticky top-0 hidden h-screen flex-col overflow-y-auto border-r border-line/60 lg:flex">
        {brand}
        <NavList groups={groups} />
        {footer}
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-bg/60 backdrop-blur-sm" onClick={() => setDrawer(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-[82vw] max-w-[300px] animate-fade-up flex-col overflow-y-auto border-r border-line/60 bg-panel">
            <div className="flex items-center justify-between pr-3">
              {brand}
              <button className="rounded-lg p-2 text-muted hover:bg-panel2" onClick={() => setDrawer(false)} aria-label="Close menu">
                <X size={20} />
              </button>
            </div>
            <NavList groups={groups} onNavigate={() => setDrawer(false)} />
            {footer}
          </aside>
        </div>
      )}

      <div className="min-w-0">
        <header className="glass sticky top-0 z-30 flex items-center gap-2 border-b border-line/60 px-4 py-3 sm:px-8">
          <button className="rounded-xl p-2 text-muted hover:bg-panel2 hover:text-fg lg:hidden" onClick={() => setDrawer(true)} aria-label="Open menu">
            <Menu size={20} />
          </button>
          <p className="hidden min-w-0 truncate text-sm sm:block">
            <span className="text-muted">{isStaff ? 'Staff' : 'Student'}</span>
            {pageLabel && (
              <>
                <span className="mx-2 text-line">/</span>
                <span className="font-semibold text-fg">{pageLabel}</span>
              </>
            )}
          </p>
          <span className="flex-1" />
          <NotificationBell />
          <button
            className="rounded-xl p-2 text-muted transition-colors hover:bg-panel2 hover:text-ink"
            onClick={toggle}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
          </button>
          <div className="relative">
            <button
              className="flex items-center gap-2.5 rounded-xl py-1 pl-2 pr-1 transition-colors hover:bg-panel2/70"
              onClick={() => setMenu((m) => !m)}
              aria-expanded={menu}
            >
              <span className="hidden text-right leading-tight sm:block">
                <span className="block max-w-[180px] truncate text-sm font-semibold">{user?.full_name}</span>
                <span className="block text-xs capitalize text-muted">{user?.role?.toLowerCase()}</span>
              </span>
              <span className="rounded-full bg-gradient-to-br from-glow1 via-glow2 to-glow3 p-[2px]">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-panel font-display text-sm font-bold">
                  {(user?.full_name || '?').slice(0, 1)}
                </span>
              </span>
            </button>
            {menu && (
              <div className="glass absolute right-0 z-30 mt-2 w-56 animate-fade-up overflow-hidden rounded-2xl border border-line/70 p-1.5 shadow-2xl">
                <button className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-panel2" onClick={() => navigate('/account')}>
                  <KeyRound size={16} /> Change password
                </button>
                <button
                  className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-absent hover:bg-absent/10"
                  onClick={() => {
                    logout()
                    navigate('/login')
                  }}
                >
                  <LogOut size={16} /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <main key={location.pathname} className="mx-auto w-full max-w-[1280px] animate-fade-up px-4 py-7 sm:px-8 sm:py-10">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
