import { Component, lazy, Suspense } from 'react'
import { Link, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { Spinner } from './components/ui'
import { useAuth } from './context/AuthContext'
import Login from './pages/Login'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const GroupAttendance = lazy(() => import('./pages/GroupAttendance'))
const LateEntry = lazy(() => import('./pages/LateEntry'))
const LiveFeed = lazy(() => import('./pages/LiveFeed'))
const Sessions = lazy(() => import('./pages/Sessions'))
const Students = lazy(() => import('./pages/Students'))
const RegisterStudent = lazy(() => import('./pages/RegisterStudent'))
const ReviewQueue = lazy(() => import('./pages/ReviewQueue'))
const Overrides = lazy(() => import('./pages/Overrides'))
const Reports = lazy(() => import('./pages/Reports'))
const Analytics = lazy(() => import('./pages/Analytics'))
const Admin = lazy(() => import('./pages/Admin'))
const StudentPortal = lazy(() => import('./pages/StudentPortal'))
const QrMark = lazy(() => import('./pages/QrMark'))
const Account = lazy(() => import('./pages/Account'))
const Courses = lazy(() => import('./pages/Courses'))
const JoinCourse = lazy(() => import('./pages/JoinCourse'))
const Signup = lazy(() => import('./pages/Signup'))

const STAFF = ['ADMIN', 'TEACHER']

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-8">
          <h1 className="text-xl">This page crashed</h1>
          <p className="mt-2 text-muted">{String(this.state.error.message || this.state.error)}</p>
          <button className="btn btn-quiet mt-4" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function Home() {
  const { user } = useAuth()
  return user?.role === 'STUDENT' ? <Navigate to="/me" replace /> : <Dashboard />
}

function NotFound() {
  return (
    <div className="py-10">
      <h1 className="text-2xl">Page not found</h1>
      <p className="mt-2 text-muted">The address does not match any page.</p>
      <Link className="btn btn-quiet mt-4" to="/">
        Go to the start page
      </Link>
    </div>
  )
}

const guard = (el, roles) => <ProtectedRoute roles={roles}>{el}</ProtectedRoute>

export default function App() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<div className="p-8"><Spinner /></div>}>
        <Routes>
          <Route path="/login" element={<Login />} />
          {/* public: a student creates their own account (admin approves it) */}
          <Route path="/signup" element={<Signup />} />
          {/* public: where a scanned course QR lands */}
          <Route path="/join" element={<JoinCourse />} />
          <Route path="/join/:code" element={<JoinCourse />} />
          <Route element={guard(<Layout />)}>
            <Route index element={<Home />} />
            <Route path="/attendance/group" element={guard(<GroupAttendance />, STAFF)} />
            <Route path="/attendance/late" element={guard(<LateEntry />, STAFF)} />
            <Route path="/live" element={guard(<LiveFeed />, STAFF)} />
            <Route path="/sessions" element={guard(<Sessions />, STAFF)} />
            <Route path="/courses" element={guard(<Courses />, STAFF)} />
            <Route path="/students" element={guard(<Students />, STAFF)} />
            <Route path="/students/register" element={guard(<RegisterStudent />, STAFF)} />
            <Route path="/review" element={guard(<ReviewQueue />, STAFF)} />
            <Route path="/overrides" element={<Overrides />} />
            <Route path="/reports" element={guard(<Reports />, STAFF)} />
            <Route path="/analytics" element={guard(<Analytics />, STAFF)} />
            <Route path="/admin" element={guard(<Admin />, ['ADMIN'])} />
            {/* same page, opened straight on the approval queue (sidebar entry) */}
            <Route path="/approvals" element={guard(<Admin initialTab="pending" />, ['ADMIN'])} />
            <Route path="/me" element={guard(<StudentPortal />, ['STUDENT'])} />
            <Route path="/qr" element={guard(<QrMark />, ['STUDENT'])} />
            <Route path="/qr/:sessionId/:code" element={guard(<QrMark />, ['STUDENT'])} />
            <Route path="/account" element={<Account />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </ErrorBoundary>
  )
}
