import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { CalendarClock, CircleCheckBig, FileUp, LoaderCircle } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';
import api from '../../lib/axios';

export default function CandidateDashboard() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState(null);

  useEffect(() => {
    const fetchDashboard = async () => {
      try {
        const response = await api.get('/candidate/dashboard');
        setDashboard(response.data);
      } catch (_error) {
        setDashboard(null);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboard();
  }, []);

  const progress = useMemo(
    () => [
      { label: 'Profile Created', done: Boolean(dashboard?.stats?.profileCreated), icon: <CircleCheckBig size={16} /> },
      { label: 'Resume Uploaded', done: Boolean(dashboard?.stats?.resumeUploaded), icon: <FileUp size={16} /> },
      { label: 'Interview Started', done: Boolean(dashboard?.stats?.interviewBooked), icon: <CalendarClock size={16} /> },
    ],
    [dashboard],
  );

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-slate-500">
        Loading candidate dashboard...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-3xl font-black tracking-tight text-slate-900">Candidate Dashboard</h1>
        <p className="mt-2 text-slate-600">
          Welcome {user?.email}. Track your hiring pipeline status below.
        </p>
      </motion.div>

      <div className="grid gap-4 md:grid-cols-3">
        {progress.map((item, index) => (
          <motion.div
            key={item.label}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.07 }}
          >
            <Card className="h-full">
              <div
                className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${
                  item.done ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
                }`}
              >
                {item.done ? item.icon : <LoaderCircle size={16} className="animate-spin" />}
                {item.done ? 'Completed' : 'Pending'}
              </div>
              <h3 className="mt-4 text-base font-bold text-slate-900">{item.label}</h3>
            </Card>
          </motion.div>
        ))}
      </div>

      <Card className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Next step</h2>
          <p className="text-sm text-slate-600">
            {dashboard?.stats?.resumeUploaded
              ? 'Great progress. Start your interview to complete this stage.'
              : 'Upload your resume PDF, then start your interview.'}
          </p>
          {dashboard?.latestUpload?.file_url && (
            <a
              href={dashboard.latestUpload.file_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex text-sm font-semibold text-teal-700 hover:text-teal-800"
            >
              View stored resume
            </a>
          )}
        </div>
        <div className="flex gap-2">
          <Link to="/profile-upload">
            <Button variant="secondary">Upload Profile</Button>
          </Link>
          <Link to="/interview">
            <Button>Start Interview</Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}
