import React from 'react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Search, Star } from 'lucide-react';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';

export default function AdminDashboard() {
  const candidates = [
    { id: 'c1', name: 'Aanya Sharma', role: 'Frontend Engineer', score: 91, stage: 'Interviewed' },
    { id: 'c2', name: 'Raghav Patel', role: 'Data Engineer', score: 86, stage: 'Resume Screened' },
    { id: 'c3', name: 'Sara Khan', role: 'ML Engineer', score: 94, stage: 'Interviewed' },
    { id: 'c4', name: 'Nikhil Roy', role: 'Backend Engineer', score: 82, stage: 'Assessment' },
  ];

  const [query, setQuery] = useState('');

  const filteredCandidates = useMemo(
    () =>
      candidates.filter((candidate) => {
        const searchable = `${candidate.name} ${candidate.role} ${candidate.stage}`.toLowerCase();
        return searchable.includes(query.toLowerCase());
      }),
    [query],
  );

  const recommendedCandidates = [...candidates].sort((a, b) => b.score - a.score).slice(0, 2);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-3xl font-black text-slate-900">Admin Dashboard</h1>
        <p className="mt-2 text-slate-600">Search, review, and prioritize candidates.</p>
      </motion.div>

      <Card>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <Input
            placeholder="Search by name, role, stage"
            className="pl-9"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-3 pr-4 font-semibold">Candidate</th>
                <th className="py-3 pr-4 font-semibold">Role</th>
                <th className="py-3 pr-4 font-semibold">Stage</th>
                <th className="py-3 pr-4 font-semibold">AI Score</th>
              </tr>
            </thead>
            <tbody>
              {filteredCandidates.map((candidate) => (
                <tr key={candidate.id} className="border-b border-slate-100">
                  <td className="py-3 pr-4 font-medium text-slate-800">
                    <Link className="hover:text-teal-700" to={`/admin/candidate/${candidate.id}`}>
                      {candidate.name}
                    </Link>
                  </td>
                  <td className="py-3 pr-4 text-slate-600">{candidate.role}</td>
                  <td className="py-3 pr-4 text-slate-600">{candidate.stage}</td>
                  <td className="py-3 pr-4">
                    <span className="rounded-full bg-teal-100 px-2.5 py-1 text-xs font-semibold text-teal-800">
                      {candidate.score}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {!filteredCandidates.length && (
            <p className="py-6 text-center text-sm text-slate-500">No candidates match your filter.</p>
          )}
        </div>
      </Card>

      <Card>
        <div className="mb-4 inline-flex items-center gap-2 text-slate-900">
          <Star size={18} className="text-amber-500" />
          <h2 className="text-lg font-bold">Recommended Candidates</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {recommendedCandidates.map((candidate) => (
            <div key={candidate.id} className="rounded-xl border border-slate-200 p-4">
              <p className="font-bold text-slate-900">{candidate.name}</p>
              <p className="text-sm text-slate-600">{candidate.role}</p>
              <p className="mt-2 text-sm font-semibold text-teal-700">AI Match Score: {candidate.score}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
