import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { Toaster } from 'react-hot-toast';

// Layouts
import Navbar from './components/layout/Navbar';

// Pages
import Landing from './pages/Landing';
import Login from './pages/auth/Login';
import Signup from './pages/auth/Signup';
import CandidateDashboard from './pages/candidate/Dashboard';
import ProfileUpload from './pages/candidate/ProfileUpload';
import Schedule from './pages/candidate/Schedule';
import AdminDashboard from './pages/admin/Dashboard';
import CandidateDetails from './pages/admin/CandidateDetails';

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
      <div className="flex min-h-screen w-full flex-col bg-slate-50">
        <Navbar />
        <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 pb-10 pt-6 sm:px-6 lg:px-8">
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
              path="/schedule"
              element={
              <ProtectedRoute allowedRoles={['candidate']}>
                <Schedule />
              </ProtectedRoute>
            }
            />

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