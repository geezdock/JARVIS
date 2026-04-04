import React from 'react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { CalendarDays } from 'lucide-react';
import toast from 'react-hot-toast';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';
import api from '../../lib/axios';
import { useAuth } from '../../contexts/AuthContext';

export default function Schedule() {
  const navigate = useNavigate();
  const { clearInterviewLock } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [currentTime, setCurrentTime] = useState(() => new Date());
  const [timeOffsetMs, setTimeOffsetMs] = useState(0);
  const [startedAt, setStartedAt] = useState(null);
  const [latestSession, setLatestSession] = useState(null);
  const [interviewRole, setInterviewRole] = useState('General Candidate');
  const [interviewPlan, setInterviewPlan] = useState(null);

  useEffect(() => {
    const fetchInterviewContext = async () => {
      try {
        const response = await api.get('/candidate/interview-slots');
        const latest = response.data?.latestStarted;
        const latestSessionRow = response.data?.latestSession;
        const plan = response.data?.interviewPlan;
        setLatestSession(latestSessionRow || null);
        if (latest?.slot_time) {
          setStartedAt(latest.slot_time);
        } else {
          clearInterviewLock();
        }
        if (plan) {
          setInterviewPlan(plan);
          setInterviewRole(plan.role || 'General Candidate');
        }
      } catch (_error) {
        setInterviewPlan(null);
        setLatestSession(null);
        clearInterviewLock();
      }
    };

    const fetchServerTime = async () => {
      try {
        const response = await api.get('/time');
        const serverUtc = new Date(response.data?.utc ?? new Date().toISOString()).getTime();
        const offset = serverUtc - Date.now();
        setTimeOffsetMs(offset);
        setCurrentTime(new Date(Date.now() + offset));
      } catch (_error) {
        setTimeOffsetMs(0);
      }
    };

    fetchInterviewContext();
    fetchServerTime();
  }, [clearInterviewLock]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setCurrentTime(new Date(Date.now() + timeOffsetMs));
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [timeOffsetMs]);

  const onStartInterview = async () => {
    try {
      setSubmitting(true);
      if (latestSession?.status === 'completed') {
        toast('Interview already submitted for this application stage.');
        navigate('/candidate', { replace: true });
        return;
      }
      if (latestSession?.status === 'terminated') {
        toast('Interview was previously terminated for this stage.');
      }
      toast.success('Opening interview room');
      navigate('/interview/live');
    } catch (_error) {
      toast.error('Unable to start interview right now');
    } finally {
      setSubmitting(false);
    }
  };

  const formatUtcTime = (value) => {
    if (!value) {
      return '';
    }

    try {
      // Avoid combining style shortcuts with timezone name because some runtimes reject it.
      return new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        timeZone: 'UTC',
        timeZoneName: 'short',
      }).format(new Date(value));
    } catch (_error) {
      return `${new Date(value).toUTCString()} UTC`;
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-black text-slate-900">Interview</h1>
        <p className="mt-1 text-sm text-slate-600">Start your interview when you are ready.</p>
      </motion.div>

      <Card>
        <div className="mb-4 flex items-center gap-2 text-slate-800">
          <CalendarDays size={18} className="text-teal-700" />
          <h2 className="text-lg font-bold">Interview Session</h2>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          Once you click Start Interview, your session will be marked as active and saved to your timeline.
        </div>

        <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-900">
          <p className="text-xs font-semibold uppercase tracking-wide">Interview role</p>
          <p className="mt-1 font-semibold">{interviewRole}</p>
          {interviewPlan?.flow?.length > 0 && (
            <p className="mt-1 text-xs text-indigo-700">Flow: {interviewPlan.flow.join(' -> ')}</p>
          )}
        </div>

        <div className="mt-4 rounded-xl border border-teal-100 bg-white p-4 text-sm text-slate-700">
          <p className="text-xs font-semibold uppercase tracking-wide text-teal-800">Current server time</p>
          <p className="mt-1 font-medium text-slate-900">{currentTime.toLocaleString()}</p>
        </div>

        <Button className="mt-5" onClick={onStartInterview} disabled={submitting}>
          {submitting
            ? 'Opening...'
            : latestSession?.status === 'completed'
              ? 'Interview Completed'
              : startedAt
                ? 'Enter Interview Room'
                : 'Start Interview'}
        </Button>

        {latestSession?.status === 'completed' && (
          <p className="mt-3 text-sm text-slate-600">
            This interview stage is already completed. You can view progress from your dashboard.
          </p>
        )}

        {startedAt && (
          <div className="mt-5 rounded-xl border border-teal-200 bg-teal-50 p-4">
            <p className="text-sm font-semibold text-teal-900">Interview Started At</p>
            <p className="mt-2 text-sm text-teal-800">{formatUtcTime(startedAt)}</p>

            {interviewPlan?.questions?.length > 0 && (
              <div className="mt-4 rounded-lg border border-white/70 bg-white/70 p-3">
                <p className="text-sm font-semibold text-teal-900">Role-based questions</p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-teal-800">
                  {interviewPlan.questions.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
