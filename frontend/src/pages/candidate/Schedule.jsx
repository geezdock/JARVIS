import React from 'react';
import { useState } from 'react';
import { motion } from 'framer-motion';
import { CalendarDays, Clock3 } from 'lucide-react';
import toast from 'react-hot-toast';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';

export default function Schedule() {
  const slots = [
    'Mon 10:00 AM',
    'Mon 2:00 PM',
    'Tue 11:00 AM',
    'Wed 4:00 PM',
    'Thu 9:30 AM',
    'Fri 3:00 PM',
  ];

  const [selectedSlot, setSelectedSlot] = useState('');

  const onSchedule = () => {
    if (!selectedSlot) {
      toast.error('Please select a slot');
      return;
    }

    toast.success(`Interview scheduled for ${selectedSlot}`);
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-black text-slate-900">Interview Scheduling</h1>
        <p className="mt-1 text-sm text-slate-600">Select a preferred interview window.</p>
      </motion.div>

      <Card>
        <div className="mb-4 flex items-center gap-2 text-slate-800">
          <CalendarDays size={18} className="text-teal-700" />
          <h2 className="text-lg font-bold">Available Slots</h2>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
          {slots.map((slot) => (
            <button
              key={slot}
              type="button"
              onClick={() => setSelectedSlot(slot)}
              className={`rounded-xl border px-4 py-3 text-left text-sm font-semibold transition ${
                selectedSlot === slot
                  ? 'border-teal-500 bg-teal-50 text-teal-800'
                  : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
              }`}
            >
              <span className="inline-flex items-center gap-1.5">
                <Clock3 size={14} />
                {slot}
              </span>
            </button>
          ))}
        </div>

        <Button className="mt-5" onClick={onSchedule}>
          Confirm Schedule
        </Button>
      </Card>
    </div>
  );
}
