import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, Bot, FileText, Sparkles, UserCheck } from 'lucide-react';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';

export default function Landing() {
  const features = [
    {
      icon: <Sparkles size={18} />,
      title: 'AI Resume Screening',
      desc: 'Auto-rank profiles using semantic scoring and role-fit insights.',
    },
    {
      icon: <Bot size={18} />,
      title: 'Interview Intelligence',
      desc: 'Transcripts, confidence scores, and candidate highlights in one place.',
    },
    {
      icon: <UserCheck size={18} />,
      title: 'Role-Based Workflow',
      desc: 'Candidate and Admin journeys built for clarity and speed.',
    },
  ];

  return (
    <div className="space-y-8">
      <motion.section
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45 }}
        className="relative overflow-hidden rounded-3xl border border-slate-200 bg-gradient-to-br from-teal-50 via-cyan-50 to-white p-8 sm:p-12"
      >
        <div className="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-teal-200/40 blur-3xl" />
        <div className="absolute -bottom-24 -left-12 h-72 w-72 rounded-full bg-cyan-200/40 blur-3xl" />

        <div className="relative z-10 max-w-3xl">
          <p className="inline-flex items-center rounded-full border border-teal-300/60 bg-white/80 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-teal-700">
            AI Recruitment Platform
          </p>
          <h1 className="mt-4 text-4xl font-black leading-tight tracking-tight text-slate-900 sm:text-5xl">
            Hire Faster With Transparent AI Candidate Insights
          </h1>
          <p className="mt-4 max-w-2xl text-base text-slate-700 sm:text-lg">
            Jarvis Recruit combines resume intelligence, interview summaries, and ranking signals so teams can shortlist top candidates in minutes.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link to="/signup">
              <Button size="lg" className="gap-2">
                Start As Candidate <ArrowRight size={16} />
              </Button>
            </Link>
            <Link to="/login">
              <Button size="lg" variant="secondary" className="gap-2">
                Admin Login <FileText size={16} />
              </Button>
            </Link>
          </div>
        </div>
      </motion.section>

      <section className="grid gap-4 md:grid-cols-3">
        {features.map((feature, index) => (
          <motion.div
            key={feature.title}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + index * 0.08 }}
          >
            <Card className="h-full">
              <div className="inline-flex rounded-lg bg-teal-100 p-2 text-teal-700">{feature.icon}</div>
              <h3 className="mt-4 text-lg font-bold text-slate-900">{feature.title}</h3>
              <p className="mt-2 text-sm text-slate-600">{feature.desc}</p>
            </Card>
          </motion.div>
        ))}
      </section>
    </div>
  );
}
