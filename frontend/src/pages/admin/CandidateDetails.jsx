import React from 'react';
import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ChevronLeft, FileText, MicVocal, Sparkle } from 'lucide-react';
import Card from '../../components/ui/Card';

export default function CandidateDetails() {
  const { id } = useParams();

  const candidate = useMemo(
    () => ({
      id,
      name: id === 'c3' ? 'Sara Khan' : 'Aanya Sharma',
      position: id === 'c3' ? 'ML Engineer' : 'Frontend Engineer',
      score: id === 'c3' ? 94 : 91,
      transcript:
        'Candidate demonstrated strong ownership, clear communication, and practical problem solving with robust trade-off reasoning.',
      summary:
        'High confidence in system design, modern frontend patterns, and collaborative debugging workflows.',
    }),
    [id],
  );

  return (
    <div className="space-y-6">
      <Link to="/admin" className="inline-flex items-center gap-1 text-sm font-medium text-slate-600 hover:text-slate-900">
        <ChevronLeft size={16} /> Back to dashboard
      </Link>

      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-3xl font-black text-slate-900">{candidate.name}</h1>
        <p className="mt-2 text-slate-600">Applied for {candidate.position}</p>
      </motion.div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-4 inline-flex items-center gap-2 text-slate-900">
            <FileText size={18} className="text-teal-700" />
            <h2 className="text-lg font-bold">Resume Preview</h2>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700">
            <p className="font-semibold">Professional Summary</p>
            <p className="mt-1">
              Product-minded engineer with 4+ years of experience building high-performance web applications and scalable hiring workflows.
            </p>
            <p className="mt-4 font-semibold">Key Skills</p>
            <p className="mt-1">React, TypeScript, ML-assisted analytics, API design, stakeholder communication</p>
          </div>
        </Card>

        <Card>
          <div className="inline-flex items-center gap-2 text-slate-900">
            <Sparkle size={18} className="text-amber-500" />
            <h2 className="text-lg font-bold">AI Score</h2>
          </div>
          <p className="mt-4 text-5xl font-black text-teal-700">{candidate.score}</p>
          <p className="mt-2 text-sm text-slate-600">Top percentile fit for role requirements.</p>
        </Card>
      </div>

      <Card>
        <div className="inline-flex items-center gap-2 text-slate-900">
          <MicVocal size={18} className="text-teal-700" />
          <h2 className="text-lg font-bold">AI Interview Transcript Summary</h2>
        </div>
        <p className="mt-3 text-sm leading-6 text-slate-700">{candidate.transcript}</p>
        <p className="mt-3 rounded-lg bg-teal-50 p-3 text-sm font-medium text-teal-800">{candidate.summary}</p>
      </Card>
    </div>
  );
}
