import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { CalendarClock, CircleCheckBig, FileUp, LoaderCircle } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';

export default function CandidateDashboard() {
  const { user } = useAuth();

  const progress = [
    { label: 'Profile Created', done: true, icon: <CircleCheckBig size={16} /> },
    { label: 'Resume Uploaded', done: false, icon: <FileUp size={16} /> },
    { label: 'Interview Slot Booked', done: false, icon: <CalendarClock size={16} /> },
  ];

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
          <p className="text-sm text-slate-600">Upload your resume PDF and lock an interview slot.</p>
        </div>
        <div className="flex gap-2">
          <Link to="/profile-upload">
            <Button variant="secondary">Upload Profile</Button>
          </Link>
          <Link to="/schedule">
            <Button>Schedule Interview</Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}
