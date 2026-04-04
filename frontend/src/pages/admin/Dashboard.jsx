import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Search, Star, X } from 'lucide-react';
import toast from 'react-hot-toast';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import api from '../../lib/axios';

const CANDIDATE_STAGES = [
  'profile_pending',
  'under_review',
  'interview_scheduled',
  'interview_completed',
  'offer_extended',
  'rejected',
];

export default function AdminDashboard() {
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [selectedStage, setSelectedStage] = useState('');
  const [sortOrder, setSortOrder] = useState('high_to_low');
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 8;
  const [bulkStage, setBulkStage] = useState('under_review');
  const [selectedCandidateIds, setSelectedCandidateIds] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [searchApplying, setSearchApplying] = useState(false);
  const [bulkApplying, setBulkApplying] = useState(false);
  const [bulkJob, setBulkJob] = useState(null);

  useEffect(() => {
    if (!bulkJob?.id || !['queued', 'running'].includes(bulkJob.status)) {
      return undefined;
    }

    const intervalId = window.setInterval(async () => {
      try {
        const response = await api.get(`/admin/background-jobs/${bulkJob.id}`);
        const job = response.data;
        setBulkJob(job);

        if (job.status === 'completed') {
          window.clearInterval(intervalId);
          setBulkApplying(false);
          await fetchCandidates();

          const result = job.result || {};
          if (job.type === 'candidate_bulk_stage_update') {
            toast.success(`Bulk stage update completed: ${result.updatedCount || 0} updated`);
          } else {
            toast.success('Bulk job completed');
          }
        }

        if (job.status === 'failed') {
          window.clearInterval(intervalId);
          setBulkApplying(false);
          toast.error(job.error || 'Bulk job failed');
        }
      } catch (error) {
        window.clearInterval(intervalId);
        setBulkApplying(false);
        setBulkJob(null);
        toast.error(error.message || 'Unable to fetch bulk job status');
      }
    }, 1500);

    return () => window.clearInterval(intervalId);
  }, [bulkJob?.id, bulkJob?.status]);

  const fetchCandidates = async () => {
    try {
      setSearchApplying(true);
      const params = new URLSearchParams();
      if (query.trim()) params.append('search', query);
      if (selectedStage) params.append('stage', selectedStage);

      const url = `/admin/candidates${params.toString() ? `?${params.toString()}` : ''}`;
      const response = await api.get(url);
      setCandidates(response.data?.candidates ?? []);
      setCurrentPage(1);
      setSelectedCandidateIds([]);
      setLoadError('');
    } catch (error) {
      setCandidates([]);
      setLoadError(error.message || 'Unable to load candidates.');
    } finally {
      setLoading(false);
      setSearchApplying(false);
    }
  };

  useEffect(() => {
    fetchCandidates();
  }, []);

  const handleSearch = async () => {
    setCandidates([]);
    setLoading(true);
    await fetchCandidates();
  };

  const handleClearFilters = async () => {
    setQuery('');
    setSelectedStage('');
    setCandidates([]);
    setCurrentPage(1);
    setSelectedCandidateIds([]);
    setLoading(true);
    setLoadError('');
    
    // Fetch all candidates without filters
    try {
      setSearchApplying(true);
      const response = await api.get('/admin/candidates');
      setCandidates(response.data?.candidates ?? []);
    } catch (error) {
      setCandidates([]);
      setLoadError(error.message || 'Unable to load candidates.');
    } finally {
      setLoading(false);
      setSearchApplying(false);
    }
  };

  const handleSortChange = (event) => {
    setSortOrder(event.target.value);
    setCurrentPage(1);
  };

  const toggleCandidateSelection = (candidateId) => {
    setSelectedCandidateIds((currentSelection) =>
      currentSelection.includes(candidateId)
        ? currentSelection.filter((id) => id !== candidateId)
        : [...currentSelection, candidateId],
    );
  };

  const toggleVisibleSelection = () => {
    const visibleIds = paginatedCandidates.map((candidate) => candidate.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedCandidateIds.includes(id));

    setSelectedCandidateIds(
      allVisibleSelected ? selectedCandidateIds.filter((id) => !visibleIds.includes(id)) : Array.from(new Set([...selectedCandidateIds, ...visibleIds])),
    );
  };

  const handleBulkStageUpdate = async () => {
    if (!selectedCandidateIds.length) {
      toast.error('Select at least one candidate first');
      return;
    }

    try {
      setBulkApplying(true);
      const response = await api.post('/admin/candidates/bulk-stage', {
        candidateIds: selectedCandidateIds,
        stage: bulkStage,
        runInBackground: true,
      });
      setBulkJob(response.data || null);
      setSelectedCandidateIds([]);
      toast.success('Bulk stage update queued');
    } catch (error) {
      toast.error(error.message || 'Unable to update selected candidates');
      setBulkApplying(false);
      setBulkJob(null);
    }
  };

  const hasActiveFilters = query || selectedStage;

  const sortedCandidates = useMemo(() => {
    return [...candidates].sort((a, b) => {
      const aScore = typeof a.score === 'number' ? a.score : 0;
      const bScore = typeof b.score === 'number' ? b.score : 0;
      return sortOrder === 'low_to_high' ? aScore - bScore : bScore - aScore;
    });
  }, [candidates, sortOrder]);

  const totalPages = Math.max(1, Math.ceil(sortedCandidates.length / pageSize));
  const paginatedCandidates = sortedCandidates.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const pageStart = sortedCandidates.length ? (currentPage - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(currentPage * pageSize, sortedCandidates.length);
  const recommendedCandidates = [...sortedCandidates].slice(0, 2);
  const allVisibleSelected = paginatedCandidates.length > 0 && paginatedCandidates.every((candidate) => selectedCandidateIds.includes(candidate.id));
  const someVisibleSelected = paginatedCandidates.some((candidate) => selectedCandidateIds.includes(candidate.id)) && !allVisibleSelected;

  if (loading && !candidates.length) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-slate-500">
        Loading admin dashboard...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-3xl font-black text-slate-900">Admin Dashboard</h1>
        <p className="mt-2 text-slate-600">Search, filter, review, and prioritize candidates.</p>
      </motion.div>

      <Card>
        {loadError ? (
          <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {loadError}
          </div>
        ) : null}

        <div className="space-y-4">
          <div className="space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
              <Input
                placeholder="Search by name or skills..."
                className="pl-9"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Stage</label>
                <select
                  value={selectedStage}
                  onChange={(e) => setSelectedStage(e.target.value)}
                  className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-opacity-30"
                >
                  <option value="">All Stages</option>
                  {CANDIDATE_STAGES.map((stage) => (
                    <option key={stage} value={stage}>
                      {stage.replaceAll('_', ' ')}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Sort By</label>
                <select
                  value={sortOrder}
                  onChange={handleSortChange}
                  className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-opacity-30"
                >
                  <option value="high_to_low">Sort - High to Low Scores</option>
                  <option value="low_to_high">Sort - Low to High Scores</option>
                </select>
              </div>
            </div>

            <div className="flex gap-2">
              <Button onClick={handleSearch} disabled={searchApplying} className="flex-1">
                {searchApplying ? 'Searching...' : 'Apply Filters'}
              </Button>
              {hasActiveFilters && (
                <Button
                  onClick={handleClearFilters}
                  variant="secondary"
                  className="flex items-center gap-2"
                >
                  <X size={16} />
                  Clear
                </Button>
              )}
            </div>

            <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-600">
                Showing {pageStart}-{pageEnd} of {sortedCandidates.length} candidates
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  disabled={currentPage <= 1}
                >
                  Previous
                </Button>
                <span className="text-sm font-medium text-slate-700">
                  Page {currentPage} of {totalPages}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                  disabled={currentPage >= totalPages}
                >
                  Next
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    ref={(input) => {
                      if (input) {
                        input.indeterminate = someVisibleSelected;
                      }
                    }}
                    onChange={toggleVisibleSelection}
                    className="h-4 w-4 rounded border-slate-300 text-[#0d9488] focus:ring-[#0d9488]"
                  />
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Bulk Actions</p>
                    <p className="text-xs text-slate-500">
                      {selectedCandidateIds.length ? `${selectedCandidateIds.length} selected` : 'Select candidates in the table to update them together'}
                    </p>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-[220px_auto] md:w-auto">
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-700">New Stage</label>
                    <select
                      value={bulkStage}
                      onChange={(event) => setBulkStage(event.target.value)}
                      className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-opacity-30"
                    >
                      {CANDIDATE_STAGES.map((stage) => (
                        <option key={stage} value={stage}>
                          {stage.replaceAll('_', ' ')}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex items-end">
                    <Button
                      onClick={handleBulkStageUpdate}
                      disabled={!selectedCandidateIds.length || bulkApplying}
                      className="w-full"
                    >
                      {bulkApplying ? 'Running...' : 'Update Selected'}
                    </Button>
                  </div>
                </div>
              </div>

              {bulkJob ? (
                <div className="mt-4 rounded-lg border border-teal-200 bg-white p-3">
                  <div className="mb-2 flex items-center justify-between text-xs font-semibold text-teal-800">
                    <span>Bulk job: {bulkJob.type?.replaceAll('_', ' ') || 'unknown'}</span>
                    <span className="uppercase">{bulkJob.status}</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
                    <div
                      className="h-full rounded-full bg-teal-600 transition-all"
                      style={{ width: `${bulkJob.progress?.percent || (bulkJob.status === 'completed' ? 100 : 0)}%` }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-slate-600">
                    {bulkJob.progress?.processed || 0} / {bulkJob.progress?.total || bulkJob.context?.candidateCount || 0} processed
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="mt-6 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-3 pr-4 font-semibold">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    ref={(input) => {
                      if (input) {
                        input.indeterminate = someVisibleSelected;
                      }
                    }}
                    onChange={toggleVisibleSelection}
                    className="h-4 w-4 rounded border-slate-300 text-[#0d9488] focus:ring-[#0d9488]"
                  />
                </th>
                <th className="py-3 pr-4 font-semibold">Candidate</th>
                <th className="py-3 pr-4 font-semibold">Interview Role</th>
                <th className="py-3 pr-4 font-semibold">Stage</th>
                <th className="py-3 pr-4 font-semibold">AI Score</th>
              </tr>
            </thead>
            <tbody>
              {paginatedCandidates.map((candidate) => (
                <tr key={candidate.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-3 pr-4 align-top">
                    <input
                      type="checkbox"
                      checked={selectedCandidateIds.includes(candidate.id)}
                      onChange={() => toggleCandidateSelection(candidate.id)}
                      className="h-4 w-4 rounded border-slate-300 text-[#0d9488] focus:ring-[#0d9488]"
                    />
                  </td>
                  <td className="py-3 pr-4 font-medium text-slate-800">
                    <Link className="text-teal-700 hover:text-teal-800 underline" to={`/admin/candidate/${candidate.id}`}>
                      {candidate.name}
                    </Link>
                  </td>
                  <td className="py-3 pr-4 text-slate-600">
                    <p>{candidate.role}</p>
                    <p className="text-xs text-slate-400">Source: {candidate.interviewRoleSource?.replaceAll('_', ' ') || 'default'}</p>
                  </td>
                  <td className="py-3 pr-4">
                    <span className="inline-block rounded-full bg-blue-100 px-2.5 py-1 text-xs font-semibold text-blue-800">
                      {candidate.stage.replaceAll('_', ' ')}
                    </span>
                  </td>
                  <td className="py-3 pr-4">
                    <span className="rounded-full bg-teal-100 px-2.5 py-1 text-xs font-semibold text-teal-800">
                      {candidate.score}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {!sortedCandidates.length && !loading ? (
            <div className="py-6 text-center text-sm text-slate-500">
              <p>No candidates match your filters.</p>
              {hasActiveFilters ? (
                <p className="mt-1 text-xs text-slate-400">Try adjusting your search criteria.</p>
              ) : (
                <p className="mt-1 text-xs text-slate-400">
                  No candidate records are available yet.
                </p>
              )}
            </div>
          ) : null}
        </div>
      </Card>

      {recommendedCandidates.length > 0 ? (
        <Card>
          <div className="mb-4 inline-flex items-center gap-2 text-slate-900">
            <Star size={18} className="text-amber-500" />
            <h2 className="text-lg font-bold">Recommended Candidates</h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {recommendedCandidates.map((candidate) => (
              <div key={candidate.id} className="rounded-xl border border-slate-200 p-4 hover:border-teal-300 hover:bg-teal-50 transition">
                <p className="font-bold text-slate-900">{candidate.name}</p>
                <p className="text-sm text-slate-600">{candidate.role}</p>
                <p className="mt-2 text-sm font-semibold text-teal-700">AI Match Score: {candidate.score}</p>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
