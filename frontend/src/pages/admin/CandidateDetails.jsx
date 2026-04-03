import React from 'react';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ChevronLeft, FileText, MicVocal, Sparkle, WandSparkles } from 'lucide-react';
import toast from 'react-hot-toast';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import api from '../../lib/axios';

export default function CandidateDetails() {
  const { id } = useParams();
  const [loading, setLoading] = useState(true);
  const [details, setDetails] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    const fetchCandidateDetails = async () => {
      try {
        const response = await api.get(`/admin/candidates/${id}`);
        setDetails(response.data);
      } catch (_error) {
        setDetails(null);
      } finally {
        setLoading(false);
      }
    };

    fetchCandidateDetails();
  }, [id]);

  const onAnalyzeResume = async () => {
    try {
      setAnalyzing(true);
      const response = await api.post(`/admin/analyze-resume/${id}`, { force: true });
      setDetails(response.data);
      toast.success('Resume analysis generated');
    } catch (_error) {
      toast.error('Unable to analyze resume right now');
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-slate-500">
        Loading candidate details...
      </div>
    );
  }

  if (!details?.candidate) {
    return (
      <div className="space-y-6">
        <Link to="/admin" className="inline-flex items-center gap-1 text-sm font-medium text-slate-600 hover:text-slate-900">
          <ChevronLeft size={16} /> Back to dashboard
        </Link>
        <p className="text-slate-600">Candidate details are unavailable.</p>
      </div>
    );
  }

  const candidate = details.candidate;
  const aiSkills = candidate.aiSkills ?? [];
  const aiSummary = candidate.aiSummary || details.summary;
  const aiExperienceLevel = candidate.aiExperienceLevel || 'Mid level';

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
          <div className="mb-4 flex items-center justify-between gap-3 text-slate-900">
            <div className="inline-flex items-center gap-2">
              <FileText size={18} className="text-teal-700" />
              <h2 className="text-lg font-bold">Resume Preview</h2>
            </div>
            <Button variant="secondary" size="sm" onClick={onAnalyzeResume} disabled={analyzing} className="gap-1.5">
              <WandSparkles size={16} /> {analyzing ? 'Analyzing...' : 'Generate AI Summary'}
            </Button>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700">
            <p className="font-semibold">AI Professional Summary</p>
            <p className="mt-1">
              {details.latestUpload
                ? `Latest upload: ${details.latestUpload.file_name} (${details.latestUpload.mime_type}, ${details.latestUpload.file_size} bytes).`
                : 'No profile upload metadata is available yet for this candidate.'}
            </p>
            {details.latestUpload?.file_url && (
              <a
                href={details.latestUpload.file_url}
                target="_blank"
                rel="noreferrer"
                className="mt-3 inline-flex font-semibold text-teal-700 hover:text-teal-800"
              >
                Open stored resume
              </a>
            )}
            <p className="mt-4 font-semibold">AI Experience Level</p>
            <p className="mt-1">{aiExperienceLevel}</p>
            <p className="mt-4 font-semibold">Key Skills</p>
            {aiSkills.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {aiSkills.map((skill) => (
                  <span key={skill} className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-teal-800 ring-1 ring-teal-200">
                    {skill}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-1">Data inferred from candidate role, stage, and uploaded profile artifacts.</p>
            )}
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
        <p className="mt-3 text-sm leading-6 text-slate-700">{aiSummary}</p>
        <p className="mt-3 rounded-lg bg-teal-50 p-3 text-sm font-medium text-teal-800">
          {details.transcript || 'Resume analysis is generated from the uploaded PDF.'}
        </p>
      </Card>
    </div>
  );
}
