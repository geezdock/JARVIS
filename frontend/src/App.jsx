import { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { Toaster } from 'react-hot-toast';

// Layouts
import Navbar from './components/layout/Navbar';

// Pages
const Landing = lazy(() => import('./pages/Landing'));
const Login = lazy(() => import('./pages/auth/Login'));
const Signup = lazy(() => import('./pages/auth/Signup'));
const CandidateDashboard = lazy(() => import('./pages/candidate/Dashboard'));
const ProfileUpload = lazy(() => import('./pages/candidate/ProfileUpload'));
const Schedule = lazy(() => import('./pages/candidate/Schedule'));
const Interview = lazy(() => import('./pages/candidate/Interview'));
const AdminDashboard = lazy(() => import('./pages/admin/Dashboard'));
const CandidateDetails = lazy(() => import('./pages/admin/CandidateDetails'));

const ProtectedRoute = ({ children, allowedRoles }) => {
  const { user, role, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-slate-500">
        Checking session...
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(role)) {
    return <Navigate to="/" replace />; // Redirect if not authorized
  }

  return children;
};

const DashboardRoute = () => {
  const { role } = useAuth();

  if (role === 'admin') {
    return <Navigate to="/admin" replace />;
  }

  return <Navigate to="/candidate" replace />;
};

const InterviewLockGuard = ({ children }) => {
  const { interviewLock } = useAuth();
  const location = useLocation();

  if (interviewLock?.active && location.pathname !== '/interview/live') {
    return <Navigate to="/interview/live" replace />;
  }

  return children;
};

const NotFound = () => (
  <div className="flex min-h-[60vh] items-center justify-center px-4 text-center">
    <div>
      <h2 className="text-3xl font-black text-slate-900">Page not found</h2>
      <p className="mt-3 text-slate-600">The page you requested does not exist.</p>
    </div>
  </div>
);

function MainRoutes() {
  return (
    <Router>
      <InterviewLockGuard>
        <div className="flex min-h-screen w-full flex-col bg-slate-50">
          <Navbar />
          <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 pb-10 pt-6 sm:px-6 lg:px-8">
            <Suspense
              fallback={
                <div className="flex min-h-[50vh] items-center justify-center text-slate-500">
                  Loading page...
                </div>
              }
            >
              <Routes>
                <Route path="/" element={<Landing />} />
                <Route path="/login" element={<Login />} />
                <Route path="/signup" element={<Signup />} />

                <Route
                  path="/dashboard"
                  element={
                    <ProtectedRoute allowedRoles={['candidate', 'admin']}>
                      <DashboardRoute />
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/candidate"
                  element={
                    <ProtectedRoute allowedRoles={['candidate']}>
                      <CandidateDashboard />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/profile-upload"
                  element={
                    <ProtectedRoute allowedRoles={['candidate']}>
                      <ProfileUpload />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/interview"
                  element={
                    <ProtectedRoute allowedRoles={['candidate']}>
                      <Schedule />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/interview/live"
                  element={
                    <ProtectedRoute allowedRoles={['candidate']}>
                      <Interview />
                    </ProtectedRoute>
                  }
                />
                <Route path="/schedule" element={<Navigate to="/interview" replace />} />

                <Route
                  path="/admin"
                  element={
                    <ProtectedRoute allowedRoles={['admin']}>
                      <AdminDashboard />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/admin/candidate/:id"
                  element={
                    <ProtectedRoute allowedRoles={['admin']}>
                      <CandidateDetails />
                    </ProtectedRoute>
                  }
                />

                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </main>
          <Toaster
            position="bottom-right"
            toastOptions={{
              style: {
                borderRadius: '12px',
                background: '#0f172a',
                color: '#f8fafc',
              },
            }}
          />
        </div>
      </InterviewLockGuard>
    </Router>
  );
}

function App() {
  return (
    <AuthProvider>
      <MainRoutes />
    </AuthProvider>
  );
}

export default App;