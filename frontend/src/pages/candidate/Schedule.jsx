import React from 'react';
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { CalendarDays } from 'lucide-react';
import toast from 'react-hot-toast';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';
import api from '../../lib/axios';

export default function Schedule() {
  const [submitting, setSubmitting] = useState(false);
  const [currentTime, setCurrentTime] = useState(() => new Date());
  const [timeOffsetMs, setTimeOffsetMs] = useState(0);
  const [startedAt, setStartedAt] = useState(null);

  useEffect(() => {
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

    fetchServerTime();
  }, []);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setCurrentTime(new Date(Date.now() + timeOffsetMs));
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [timeOffsetMs]);

  const onStartInterview = async () => {
    try {
      setSubmitting(true);
      const response = await api.post('/candidate/interview-slots', {
        slotTime: new Date().toISOString(),
      });
      setStartedAt(response.data?.startedAt ?? response.data?.slot?.slot_time ?? null);
      toast.success('Interview started');
    } catch (_error) {
      toast.error('Unable to start interview right now');
    } finally {
      setSubmitting(false);
    }
  };

  const hasStartedInterview = Boolean(startedAt);

  const formatUtcTime = (value) => {
    if (!value) {
      return '';
    }

    return new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      timeStyle: 'medium',
      timeZone: 'UTC',
      timeZoneName: 'short',
    }).format(new Date(value));
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

        <div className="mt-4 rounded-xl border border-teal-100 bg-white p-4 text-sm text-slate-700">
          <p className="text-xs font-semibold uppercase tracking-wide text-teal-800">Current server time</p>
          <p className="mt-1 font-medium text-slate-900">{currentTime.toLocaleString()}</p>
        </div>

        <Button className="mt-5" onClick={onStartInterview} disabled={submitting || hasStartedInterview}>
          {submitting ? 'Starting...' : hasStartedInterview ? 'Interview Started' : 'Start Interview'}
        </Button>

        {startedAt && (
          <div className="mt-5 rounded-xl border border-teal-200 bg-teal-50 p-4">
            <p className="text-sm font-semibold text-teal-900">Interview Started At</p>
            <p className="mt-2 text-sm text-teal-800">{formatUtcTime(startedAt)}</p>
          </div>
        )}
      </Card>
    </div>
  );
}
