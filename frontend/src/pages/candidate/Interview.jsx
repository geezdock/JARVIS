import React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Camera, Mic, PhoneCall, PhoneOff, Video } from 'lucide-react';
import toast from 'react-hot-toast';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';
import api from '../../lib/axios';

const uploadBlobToSignedUrl = async (blob, sessionId, fileType = 'video', extension = 'webm') => {
  const response = await api.post('/candidate/storage/signed-interview-upload', {
    sessionId,
    fileType,
    extension,
  });
  const signedUrl = response.data?.signedUrl;
  const path = response.data?.path;
  const uploadNonce = response.data?.uploadNonce;
  if (!signedUrl) {
    throw new Error('Unable to prepare interview media upload');
  }
  if (!path || !uploadNonce) {
    throw new Error('Upload authorization is incomplete');
  }

  await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();

    xhr.open('PUT', signedUrl, true);
    xhr.setRequestHeader('x-upsert', 'false');

    formData.append('cacheControl', '3600');
    formData.append('', blob);

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
        return;
      }
      reject(new Error('Failed to upload interview recording'));
    };

    xhr.onerror = () => {
      reject(new Error('Network error during interview upload'));
    };

    xhr.send(formData);
  });

  return {
    path,
    uploadNonce,
  };
};

export default function Interview() {
  const navigate = useNavigate();
  const location = useLocation();
  const [sessionData, setSessionData] = useState(null);
  const [interviewRole, setInterviewRole] = useState('General Candidate');
  const [interviewPlan, setInterviewPlan] = useState(null);
  const [resumeSummary, setResumeSummary] = useState('');

  const [hasAcknowledgedNotice, setHasAcknowledgedNotice] = useState(false);
  const [startingSession, setStartingSession] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0);
  const [responses, setResponses] = useState([]);
  const [completing, setCompleting] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const videoRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const recordedChunksRef = useRef([]);

  const questions = useMemo(() => interviewPlan?.questions ?? [], [interviewPlan]);
  const activeQuestion = questions[activeQuestionIndex] ?? null;
  const routeSessionId = location.state?.sessionData?.session?.id || null;

  useEffect(() => {
    const fetchInterviewContext = async () => {
      try {
        const response = await api.get('/candidate/interview-slots');
        const plan = response.data?.interviewPlan;
        const latestSession = response.data?.latestSession;
        const sessionIdToValidate = routeSessionId || latestSession?.id || null;

        if (plan) {
          setInterviewPlan(plan);
          setInterviewRole(plan.role || 'General Candidate');
        }

        if (!sessionIdToValidate) {
          return;
        }

        const sessionCheck = await api.get(`/candidate/interview-session/${sessionIdToValidate}`);
        const verifiedSession = sessionCheck.data?.session;
        if (!verifiedSession?.id) {
          return;
        }

        if (verifiedSession.status === 'in_progress') {
          setSessionData({
            session: verifiedSession,
            interviewRole: sessionCheck.data?.interviewRole || latestSession?.interview_role || plan?.role || 'General Candidate',
            interviewRoleSource: sessionCheck.data?.interviewRoleSource || latestSession?.role_source || 'default',
            interviewPlan: sessionCheck.data?.interviewPlan || plan,
            resumeSummary: sessionCheck.data?.resumeSummary || latestSession?.resume_summary || '',
          });
          setInterviewRole(sessionCheck.data?.interviewRole || latestSession?.interview_role || plan?.role || 'General Candidate');
          if (sessionCheck.data?.interviewPlan) {
            setInterviewPlan(sessionCheck.data.interviewPlan);
          }
          setResumeSummary(sessionCheck.data?.resumeSummary || latestSession?.resume_summary || '');
          setHasAcknowledgedNotice(true);
        }
      } catch (_error) {
        setSessionData(null);
        setHasAcknowledgedNotice(false);
      }
    };

    fetchInterviewContext();
  }, [routeSessionId]);

  const startInterviewSession = async () => {
    try {
      setStartingSession(true);
      const response = await api.post('/candidate/interview-session/start', {
        consentGiven: true,
      });

      setSessionData(response.data);
      setInterviewRole(response.data?.interviewRole || 'General Candidate');
      setInterviewPlan(response.data?.interviewPlan ?? null);
      setResumeSummary(response.data?.resumeSummary || '');
      setHasAcknowledgedNotice(true);
    } catch (error) {
      toast.error(error.message || 'Unable to start interview session right now');
    } finally {
      setStartingSession(false);
    }
  };

  useEffect(() => {
    if (!hasAcknowledgedNotice) {
      return;
    }

    if (!sessionData?.session?.id) {
      return;
    }

    const startMedia = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: true,
          audio: true,
        });
        mediaStreamRef.current = stream;

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }

        const recorder = new MediaRecorder(stream, {
          mimeType: 'video/webm;codecs=vp8,opus',
        });
        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            recordedChunksRef.current.push(event.data);
          }
        };
        recorder.start(1000);
        mediaRecorderRef.current = recorder;

        setResponses(questions.map(() => ''));
        setConnecting(false);
        toast.success('Live interview room is ready');
      } catch (_error) {
        toast.error('Camera and microphone permission is required for interview');
        navigate('/interview', { replace: true });
      }
    };

    startMedia();

    return () => {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, [hasAcknowledgedNotice, navigate, questions, sessionData?.session?.id]);

  useEffect(() => {
    if (connecting) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [connecting]);

  useEffect(() => {
    if (!activeQuestion || !window.speechSynthesis) {
      return;
    }

    const utterance = new SpeechSynthesisUtterance(activeQuestion);
    utterance.rate = 1;
    utterance.pitch = 1;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }, [activeQuestion]);

  const onAnswerChange = (value) => {
    setResponses((prev) => {
      const next = [...prev];
      next[activeQuestionIndex] = value;
      return next;
    });
  };

  const onNextQuestion = () => {
    if (activeQuestionIndex < questions.length - 1) {
      setActiveQuestionIndex((prev) => prev + 1);
    }
  };

  const onEndInterview = async () => {
    if (!sessionData?.session?.id) {
      toast.error('Interview session context is missing');
      return;
    }

    try {
      setCompleting(true);

      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }

      await new Promise((resolve) => window.setTimeout(resolve, 300));

      const recordingBlob = new Blob(recordedChunksRef.current, { type: 'video/webm' });
      const sessionId = sessionData.session.id;
      const uploadResult = await uploadBlobToSignedUrl(recordingBlob, sessionId, 'video', 'webm');
      const storedVideoPath = uploadResult.path;
      const videoUploadNonce = uploadResult.uploadNonce;

      const transcriptText = questions
        .map((question, index) => {
          const answer = responses[index] || '(no response captured)';
          return `Q${index + 1}: ${question}\nA${index + 1}: ${answer}`;
        })
        .join('\n\n');

      const answeredCount = responses.filter((answer) => answer.trim().length > 0).length;
      const totalQuestions = questions.length || 1;
      const score = Math.round((answeredCount / totalQuestions) * 100);

      await api.post(`/candidate/interview-session/${sessionId}/complete`, {
        transcript: transcriptText,
        durationSeconds: elapsedSeconds,
        videoPath: storedVideoPath,
        videoUploadNonce,
        videoUrl: null,
        scorePayload: {
          overallScore: score,
          answeredCount,
          totalQuestions,
          role: sessionData?.interviewRole,
        },
      });

      toast.success('Interview completed and submitted');
      navigate('/candidate', { replace: true });
    } catch (error) {
      toast.error(error.message || 'Unable to complete interview session');
    } finally {
      setCompleting(false);
    }
  };

  if (!sessionData?.session?.id) {
    if (startingSession) {
      return (
        <Card>
          <h2 className="text-xl font-black text-slate-900">Starting Interview Session</h2>
          <p className="mt-2 text-sm text-slate-600">Preparing your secure interview room...</p>
        </Card>
      );
    }

    return (
      <Card>
        <h2 className="text-xl font-black text-slate-900">Before You Start</h2>
        <p className="mt-2 text-sm leading-6 text-slate-700">
          This interview records your audio, video, and transcript for hiring evaluation.
          These interview artifacts are retained only for recruitment decisions and are deleted
          once your final hiring outcome is completed (hired or not hired).
        </p>
        <p className="mt-2 text-xs text-slate-500">
          By continuing, you consent to recording and processing for evaluation purposes.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={startInterviewSession} disabled={startingSession}>
            {startingSession ? 'Starting...' : 'I Understand, Continue'}
          </Button>
          <Button variant="secondary" onClick={() => navigate('/interview')}>
            Cancel
          </Button>
        </div>
      </Card>
    );
  }

  if (!hasAcknowledgedNotice) {
    return (
      <Card>
        <h2 className="text-xl font-black text-slate-900">Before You Start</h2>
        <p className="mt-2 text-sm leading-6 text-slate-700">
          This interview records your audio, video, and transcript for hiring evaluation.
          These interview artifacts are retained only for recruitment decisions and are deleted
          once your final hiring outcome is completed (hired or not hired).
        </p>
        <p className="mt-2 text-xs text-slate-500">
          By continuing, you consent to recording and processing for evaluation purposes.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={startInterviewSession} disabled={startingSession}>
            {startingSession ? 'Starting...' : 'I Understand, Continue'}
          </Button>
          <Button variant="secondary" onClick={() => navigate('/interview')}>
            Cancel
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-black text-slate-900">Live AI Interview</h1>
        <p className="mt-1 text-sm text-slate-600">
          Role: <span className="font-semibold text-slate-800">{sessionData?.interviewRole}</span>
        </p>
      </motion.div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <div className="mb-3 inline-flex items-center gap-2 text-slate-900">
            <Camera size={18} className="text-teal-700" />
            <h2 className="text-lg font-bold">Candidate Camera + Mic</h2>
          </div>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-black">
            <video ref={videoRef} autoPlay muted playsInline className="h-[260px] w-full object-cover" />
          </div>
          <div className="mt-3 flex items-center gap-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Video size={14} /> Video On
            </span>
            <span className="inline-flex items-center gap-1">
              <Mic size={14} /> Audio On
            </span>
            <span>{Math.floor(elapsedSeconds / 60)}m {elapsedSeconds % 60}s</span>
          </div>
        </Card>

        <Card>
          <div className="mb-3 inline-flex items-center gap-2 text-slate-900">
            <PhoneCall size={18} className="text-indigo-700" />
            <h2 className="text-lg font-bold">AI Interviewer</h2>
          </div>
          <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-sm text-indigo-900">
            <p className="text-xs font-semibold uppercase tracking-wide">Resume context</p>
            <p className="mt-1 line-clamp-5">{resumeSummary || 'Resume summary unavailable for this session.'}</p>
          </div>

          {activeQuestion && (
            <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Question {activeQuestionIndex + 1} of {questions.length}
              </p>
              <p className="mt-2 text-sm font-semibold text-slate-900">{activeQuestion}</p>
              <textarea
                className="mt-3 h-24 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-teal-500"
                value={responses[activeQuestionIndex] || ''}
                onChange={(event) => onAnswerChange(event.target.value)}
                placeholder="Type candidate response transcript notes here..."
              />
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={onNextQuestion} disabled={activeQuestionIndex >= questions.length - 1}>
              Next Question
            </Button>
            <Button onClick={onEndInterview} disabled={connecting || completing} className="gap-1.5">
              <PhoneOff size={16} /> {completing ? 'Submitting...' : 'End Interview'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
