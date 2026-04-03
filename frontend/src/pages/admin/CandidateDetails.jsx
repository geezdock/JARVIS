import React from 'react';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ChevronLeft, FileText, MicVocal, PlayCircle, Sparkle, WandSparkles } from 'lucide-react';
import toast from 'react-hot-toast';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import api from '../../lib/axios';
import { INTERVIEW_ROLE_OPTIONS } from '../../lib/interviewRoles';

export default function CandidateDetails() {
  const { id } = useParams();
  const [loading, setLoading] = useState(true);
  const [details, setDetails] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [savingRole, setSavingRole] = useState(false);
  const [targetRole, setTargetRole] = useState('');
  const [adminOverrideRole, setAdminOverrideRole] = useState('');
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionDetails, setSessionDetails] = useState(null);
  const [retryingScore, setRetryingScore] = useState(false);
  const [candidateStage, setCandidateStage] = useState('');
  const [stageSaving, setStageSaving] = useState(false);

  const CANDIDATE_STAGES = [
    'profile_pending',
    'under_review',
    'interview_scheduled',
    'interview_completed',
    'offer_extended',
    'rejected',
  ];

  const formatDateTime = (value) => {
    if (!value) {
      return 'N/A';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return 'N/A';
    }
    return date.toLocaleString();
  };

  const loadInterviewSession = async (sessionId) => {
    if (!sessionId) {
      setSessionDetails(null);
      return;
    }

    try {
      setSessionLoading(true);
      const response = await api.get(`/admin/interview-session/${sessionId}`);
      setSessionDetails(response.data || null);
    } catch (_error) {
      setSessionDetails(null);
      toast.error('Unable to load interview session playback details');
    } finally {
      setSessionLoading(false);
    }
  };

  const scoreStatusPill = (status) => {
    if (status === 'completed') {
      return <span className="rounded-full bg-teal-100 px-2 py-0.5 text-xs font-semibold text-teal-800">Scored</span>;
    }
    return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">Scoring Pending</span>;
  };

  useEffect(() => {
    const fetchCandidateDetails = async () => {
      try {
        const response = await api.get(`/admin/candidates/${id}`);
        setDetails(response.data);
        setTargetRole(response.data?.candidate?.targetRole || '');
        setAdminOverrideRole(response.data?.candidate?.adminOverrideRole || '');
        setCandidateStage(response.data?.candidate?.currentStage || 'profile_pending');

        const sessions = response.data?.interviewSessions || [];
        const preferredSession =
          sessions.find((session) => session?.status === 'completed') ||
          sessions.find((session) => session?.status === 'failed') ||
          sessions[0];
        const firstSessionId = preferredSession?.id || '';
        setSelectedSessionId(firstSessionId);
        if (firstSessionId) {
          await loadInterviewSession(firstSessionId);
        } else {
          setSessionDetails(null);
        }
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

  const onSaveInterviewRole = async () => {
    try {
      setSavingRole(true);
      const response = await api.post(`/admin/candidates/${id}/interview-role`, {
        targetRole: targetRole || null,
        adminOverrideRole: adminOverrideRole || null,
      });
      setDetails(response.data);
      setTargetRole(response.data?.candidate?.targetRole || '');
      setAdminOverrideRole(response.data?.candidate?.adminOverrideRole || '');
      toast.success('Interview role settings updated');
    } catch (_error) {
      toast.error('Unable to update interview role settings');
    } finally {
      setSavingRole(false);
    }
  };

  const onSaveStage = async () => {
    try {
      setStageSaving(true);
      const response = await api.post(`/admin/candidates/${id}/stage`, {
        stage: candidateStage,
      });
      setDetails(response.data);
      setCandidateStage(response.data?.candidate?.currentStage || 'profile_pending');
      toast.success('Candidate stage updated successfully');
    } catch (_error) {
      toast.error('Unable to update candidate stage');
    } finally {
      setStageSaving(false);
    }
  };

  const onRetrySessionScoring = async () => {
    if (!selectedSessionId) {
      return;
    }

    try {
      setRetryingScore(true);
      await api.post(`/admin/interview-session/${selectedSessionId}/score/retry`);
      await loadInterviewSession(selectedSessionId);

      const refreshed = await api.get(`/admin/candidates/${id}`);
      setDetails(refreshed.data);
      toast.success('Interview scoring retried successfully');
    } catch (error) {
      toast.error(error.message || 'Unable to retry scoring right now');
    } finally {
      setRetryingScore(false);
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
  const interviewSessions = details.interviewSessions || [];
  const artifact = sessionDetails?.artifact || null;
  const scorePayload = artifact?.score_payload || {};
  const rubric = scorePayload?.scoringRubric || {};
  const rubricComponents = rubric?.components || {};
  const interviewAverages = rubric?.interviewComponentAverages || {};
  const videoUrl = sessionDetails?.videoSignedUrl?.signedUrl || null;
  const audioUrl = sessionDetails?.audioSignedUrl?.signedUrl || null;

  return (
    <div className="space-y-6">
      <Link to="/admin" className="inline-flex items-center gap-1 text-sm font-medium text-slate-600 hover:text-slate-900">
        <ChevronLeft size={16} /> Back to dashboard
      </Link>

      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-3xl font-black text-slate-900">{candidate.name}</h1>
        <p className="mt-2 text-slate-600">Interview role: {candidate.position}</p>
        <p className="mt-1 text-xs text-slate-500">Source: {candidate.interviewRoleSource?.replaceAll('_', ' ') || 'default'}</p>
      </motion.div>

      <Card>
        <h2 className="text-lg font-bold text-slate-900">Interview Role Controls</h2>
        <p className="mt-1 text-sm text-slate-600">
          Candidate target role is preferred unless admin override is set.
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="targetRole" className="mb-1.5 block text-sm font-medium text-slate-700">
              Candidate target role
            </label>
            <select
              id="targetRole"
              value={targetRole}
              onChange={(event) => setTargetRole(event.target.value)}
              className="h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-[#0d9488] focus:ring-4 focus:ring-[#0d9488]/20"
            >
              <option value="">Not set</option>
              {INTERVIEW_ROLE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="adminOverrideRole" className="mb-1.5 block text-sm font-medium text-slate-700">
              Admin override role
            </label>
            <select
              id="adminOverrideRole"
              value={adminOverrideRole}
              onChange={(event) => setAdminOverrideRole(event.target.value)}
              className="h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-[#0d9488] focus:ring-4 focus:ring-[#0d9488]/20"
            >
              <option value="">No override</option>
              {INTERVIEW_ROLE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
        </div>
        <Button className="mt-4" onClick={onSaveInterviewRole} disabled={savingRole}>
          {savingRole ? 'Saving...' : 'Save Role Settings'}
        </Button>
      </Card>

      <Card>
        <h2 className="text-lg font-bold text-slate-900">Application Stage</h2>
        <p className="mt-1 text-sm text-slate-600">
          Update the candidate's progress through the hiring pipeline.
        </p>
        <div className="mt-4">
          <label htmlFor="candidateStage" className="mb-2 block text-sm font-medium text-slate-700">
            Current Stage
          </label>
          <select
            id="candidateStage"
            value={candidateStage}
            onChange={(event) => setCandidateStage(event.target.value)}
            className="h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-[#0d9488] focus:ring-4 focus:ring-[#0d9488]/20 md:w-1/2"
          >
            {CANDIDATE_STAGES.map((stage) => (
              <option key={stage} value={stage}>
                {stage.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
          <p className="mt-2 text-xs text-slate-500">
            Pipeline: profile_pending → under_review → interview_scheduled → interview_completed → offer_extended / rejected
          </p>
        </div>
        <Button className="mt-4" onClick={onSaveStage} disabled={stageSaving} variant={candidateStage !== details?.candidate?.currentStage ? 'default' : 'secondary'}>
          {stageSaving ? 'Updating...' : 'Update Stage'}
        </Button>
      </Card>

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

      <Card>
        <div className="inline-flex items-center gap-2 text-slate-900">
          <PlayCircle size={18} className="text-indigo-700" />
          <h2 className="text-lg font-bold">Interview Playback & Scoring</h2>
        </div>

        {interviewSessions.length ? (
          <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-600">
                <tr>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Scoring</th>
                  <th className="px-3 py-2 font-semibold">Started</th>
                  <th className="px-3 py-2 font-semibold">Ended</th>
                  <th className="px-3 py-2 font-semibold">Termination</th>
                  <th className="px-3 py-2 font-semibold">Rubric</th>
                  <th className="px-3 py-2 font-semibold">Delta</th>
                </tr>
              </thead>
              <tbody>
                {interviewSessions.map((session) => {
                  const delta = session?.rubricDelta;
                  const deltaText =
                    typeof delta === 'number'
                      ? `${delta > 0 ? '+' : ''}${delta}`
                      : 'N/A';

                  return (
                    <tr key={`timeline-${session.id}`} className="border-t border-slate-200 text-slate-700">
                      <td className="px-3 py-2">{session?.status || 'unknown'}</td>
                      <td className="px-3 py-2">{scoreStatusPill(session?.scoringStatus)}</td>
                      <td className="px-3 py-2">{formatDateTime(session?.startedAt)}</td>
                      <td className="px-3 py-2">{formatDateTime(session?.endedAt)}</td>
                      <td className="px-3 py-2">{session?.terminationReason || 'N/A'}</td>
                      <td className="px-3 py-2">{typeof session?.rubricOverall === 'number' ? session.rubricOverall : 'N/A'}</td>
                      <td className="px-3 py-2">{deltaText}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        {interviewSessions.length ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {interviewSessions.map((session) => (
              <Button
                key={session.id}
                size="sm"
                variant={selectedSessionId === session.id ? 'primary' : 'secondary'}
                onClick={async () => {
                  setSelectedSessionId(session.id);
                  await loadInterviewSession(session.id);
                }}
              >
                {session.status || 'unknown'} | {session.startedAt ? new Date(session.startedAt).toLocaleString() : 'no start time'}
              </Button>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-600">No interview sessions found for this candidate yet.</p>
        )}

        {sessionLoading ? <p className="mt-4 text-sm text-slate-500">Loading session details...</p> : null}

        {!sessionLoading && selectedSessionId && sessionDetails ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className="space-y-3">
              <p className="text-sm font-semibold text-slate-800">Media Playback</p>
              {videoUrl ? (
                <video controls className="w-full rounded-xl border border-slate-200 bg-black">
                  <source src={videoUrl} type="video/webm" />
                </video>
              ) : (
                <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">No video artifact found for this session.</p>
              )}
              {audioUrl ? (
                <audio controls className="w-full">
                  <source src={audioUrl} type="audio/webm" />
                </audio>
              ) : null}
            </div>

            <div className="space-y-3">
              <p className="text-sm font-semibold text-slate-800">Scoring Rubric</p>
              <div className="flex items-center gap-2">
                {scoreStatusPill(scorePayload?.scoringStatus)}
                {scorePayload?.scoringStatus !== 'completed' ? (
                  <Button size="sm" variant="secondary" onClick={onRetrySessionScoring} disabled={retryingScore}>
                    {retryingScore ? 'Retrying...' : 'Retry Scoring'}
                  </Button>
                ) : null}
              </div>
              {scorePayload?.scoringError ? (
                <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">Last scoring error: {scorePayload.scoringError}</p>
              ) : null}
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                <p><span className="font-semibold">Overall score:</span> {scorePayload?.overallScore ?? rubric?.overallScore ?? 'N/A'}</p>
                <p><span className="font-semibold">Resume score:</span> {rubric?.resumeScore ?? rubricComponents?.resume ?? 'N/A'} / 100</p>
                <p><span className="font-semibold">Interview score:</span> {rubric?.interviewScore ?? rubricComponents?.interview ?? 'N/A'} / 100</p>
                <p><span className="font-semibold">Behavior score:</span> {rubric?.behaviorScore ?? rubricComponents?.behavior ?? 'N/A'} / 10</p>
                <p><span className="font-semibold">Answered:</span> {scorePayload?.answeredCount ?? rubric?.answeredCount ?? 0} / {scorePayload?.totalQuestions ?? rubric?.totalQuestions ?? 0}</p>
                <p className="mt-2 font-semibold">Interview category averages</p>
                <p>Technical accuracy: {interviewAverages?.technicalAccuracy ?? 'N/A'}</p>
                <p>Problem solving: {interviewAverages?.problemSolving ?? 'N/A'}</p>
                <p>Communication: {interviewAverages?.communication ?? 'N/A'}</p>
                <p>Confidence: {interviewAverages?.confidence ?? 'N/A'}</p>
                <p>Relevance: {interviewAverages?.relevance ?? 'N/A'}</p>
                <p className="mt-2 font-semibold">Behavior notes</p>
                <p>Notes: {rubric?.behaviorDetails?.behaviorNotes || 'N/A'}</p>
                <p><span className="font-semibold">Model:</span> {scorePayload?.evaluationVersion || rubric?.version || 'legacy'}</p>
              </div>

              <p className="text-sm font-semibold text-slate-800">Transcript</p>
              <div className="max-h-56 overflow-auto rounded-xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-700">
                {artifact?.transcript || 'No transcript saved for this session.'}
              </div>
            </div>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
