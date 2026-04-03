import React from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, BriefcaseBusiness, CalendarDays, LayoutDashboard, LogOut, Shield, UserRoundCheck } from 'lucide-react';
import toast from 'react-hot-toast';
import { useAuth } from '../../contexts/AuthContext';
import Button from '../ui/Button';

export default function Navbar() {
  const { user, role, logout, interviewLock } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const interviewLocked = Boolean(interviewLock?.active);
  const isCandidateInterviewRoute =
    role === 'candidate' && (location.pathname === '/interview' || location.pathname === '/interview/live');
  const isLiveInterviewLocked = role === 'candidate' && location.pathname === '/interview/live' && interviewLocked;
  const dashboardPath = role === 'admin' ? '/admin' : '/candidate';
  const backPath = '/candidate';

  const onLogout = async () => {
    try {
      await logout();
      toast.success('Logged out successfully');
      navigate('/');
    } catch (error) {
      toast.error(error.message || 'Unable to logout');
    }
  };

  const navLinkClass = ({ isActive }) =>
    `rounded-lg px-3 py-2 text-sm font-medium transition ${
      isActive ? 'bg-teal-100 text-teal-900' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
    }`;

  const brandContent = (
    <>
      <span className="rounded-lg bg-[#0d9488] p-2 text-white">
        <BriefcaseBusiness size={18} />
      </span>
      <span className="text-lg font-black tracking-tight">Jarvis Recruit AI</span>
    </>
  );

  return (
    <motion.nav
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur"
    >
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        {isLiveInterviewLocked ? (
          <div className="flex cursor-default items-center gap-2 text-slate-900" aria-label="Jarvis Recruit AI">
            {brandContent}
          </div>
        ) : (
          <Link to={user ? dashboardPath : '/'} className="flex items-center gap-2 text-slate-900">
            {brandContent}
          </Link>
        )}

        <div className="flex items-center gap-2 sm:gap-3">
        {user ? (
          <>
            {isLiveInterviewLocked ? null : isCandidateInterviewRoute ? (
              <Button variant="secondary" size="sm" onClick={() => navigate(backPath)} className="gap-1.5">
                <ArrowLeft size={16} /> Back to Dashboard
              </Button>
            ) : interviewLocked ? (
              <div className="rounded-lg bg-amber-100 px-3 py-2 text-sm font-semibold text-amber-800">
                Interview in progress
              </div>
            ) : role === 'admin' ? (
              <NavLink to="/admin" className={navLinkClass}>
                <span className="inline-flex items-center gap-1.5">
                  <Shield size={16} /> Admin
                </span>
              </NavLink>
            ) : (
              <>
                <NavLink to="/candidate" className={navLinkClass}>
                  <span className="inline-flex items-center gap-1.5">
                    <LayoutDashboard size={16} /> Dashboard
                  </span>
                </NavLink>
                <NavLink to="/profile-upload" className={navLinkClass}>
                  <span className="inline-flex items-center gap-1.5">
                    <UserRoundCheck size={16} /> Profile
                  </span>
                </NavLink>
                <NavLink to="/interview" className={navLinkClass}>
                  <span className="inline-flex items-center gap-1.5">
                    <CalendarDays size={16} /> Interview
                  </span>
                </NavLink>
              </>
            )}
              {!isLiveInterviewLocked && !isCandidateInterviewRoute ? (
                <Button variant="secondary" size="sm" onClick={onLogout} className="gap-1.5" disabled={interviewLocked}>
                  <LogOut size={16} /> Logout
                </Button>
              ) : null}
          </>
        ) : (
          <>
            <NavLink to="/login" className={navLinkClass}>
              Login
            </NavLink>
            <Button size="sm" onClick={() => navigate('/signup')}>
              Sign Up
            </Button>
          </>
        )}
        </div>
      </div>
    </motion.nav>
  );
}
