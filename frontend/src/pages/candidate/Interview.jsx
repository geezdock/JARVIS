import React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Camera, Mic, PhoneCall, PhoneOff, Video } from 'lucide-react';
import toast from 'react-hot-toast';
import { useAuth } from '../../contexts/AuthContext';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';
import api from '../../lib/axios';

const buildTranscriptFromTurns = (turns) =>
  (turns || [])
    .filter((turn) => turn?.speaker && turn?.text)
    .map((turn, index) => `${index + 1}. ${turn.speaker.toUpperCase()}: ${turn.text}`)
    .join('\n');

const resolveAiOutputMode = (value) => {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (normalized === 'openai_stream') {
    return 'openai_stream';
  }
  return 'browser_tts';
};

const DEFAULT_AI_OUTPUT_MODE = resolveAiOutputMode(import.meta.env.VITE_AI_INTERVIEW_OUTPUT_MODE);

const normalizeTranscriptText = (value) => (typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '');

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
  const { startInterviewLock, clearInterviewLock } = useAuth();
  const [sessionData, setSessionData] = useState(null);
  const [aiOutputMode, setAiOutputMode] = useState(DEFAULT_AI_OUTPUT_MODE);
  const [interviewRole, setInterviewRole] = useState('General Candidate');
  const [interviewPlan, setInterviewPlan] = useState(null);
  const [resumeSummary, setResumeSummary] = useState('');

  const [hasAcknowledgedNotice, setHasAcknowledgedNotice] = useState(false);
  const [startingSession, setStartingSession] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0);
  const [responses, setResponses] = useState([]);
  const [transcriptTurns, setTranscriptTurns] = useState([]);
  const [autosavingTranscript, setAutosavingTranscript] = useState(false);
  const [realtimeStatus, setRealtimeStatus] = useState('idle');
  const [completing, setCompleting] = useState(false);
  const [terminating, setTerminating] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const videoRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const remoteAudioRef = useRef(null);
  const rtcPeerConnectionRef = useRef(null);
  const rtcDataChannelRef = useRef(null);
  const realtimeInitRef = useRef(false);
  const realtimeModelRef = useRef('gpt-4o-realtime-preview-2024-12-17');
  const realtimeConnectedRef = useRef(false);
  const lastRealtimeAiTextRef = useRef('');
  const lastRealtimeCandidateTextRef = useRef('');
  const recordedChunksRef = useRef([]);
  const transcriptTurnsRef = useRef([]);
  const autosaveInFlightRef = useRef(false);
  const autosaveQueuedRef = useRef(false);
  const lastAutosavedTranscriptRef = useRef('');
  const lastRequestedTranscriptVersionRef = useRef(0);
  const lastAppliedTranscriptVersionRef = useRef(0);
  const sessionFinalizedRef = useRef(false);

  const questions = useMemo(() => interviewPlan?.questions ?? [], [interviewPlan]);
  const activeQuestion = questions[activeQuestionIndex] ?? null;
  const routeSessionId = location.state?.sessionData?.session?.id || null;
  const transcriptSnapshot = useMemo(() => buildTranscriptFromTurns(transcriptTurns), [transcriptTurns]);

  useEffect(() => {
    transcriptTurnsRef.current = transcriptTurns;
  }, [transcriptTurns]);

  const appendRealtimeTurn = useCallback((speaker, text, idPrefix) => {
    const normalizedText = normalizeTranscriptText(text);
    if (!normalizedText) {
      return;
    }

    setTranscriptTurns((prev) => [
      ...prev,
      {
        id: `${idPrefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        speaker,
        text: normalizedText,
        timestamp: new Date().toISOString(),
      },
    ]);
  }, []);

  const cleanupRealtimeTransport = useCallback(() => {
    realtimeConnectedRef.current = false;
    realtimeInitRef.current = false;

    if (rtcDataChannelRef.current) {
      try {
        rtcDataChannelRef.current.close();
      } catch (_error) {
        // no-op
      }
      rtcDataChannelRef.current = null;
    }

    if (rtcPeerConnectionRef.current) {
      try {
        rtcPeerConnectionRef.current.close();
      } catch (_error) {
        // no-op
      }
      rtcPeerConnectionRef.current = null;
    }

    if (remoteAudioRef.current) {
      remoteAudioRef.current.srcObject = null;
    }
  }, []);

  const handleRealtimeEvent = useCallback(
    (eventPayload) => {
      if (!eventPayload || typeof eventPayload !== 'object') {
        return;
      }

      if (eventPayload.type === 'error') {
        setRealtimeStatus('fallback');
        return;
      }

      if (eventPayload.type === 'response.audio_transcript.done' || eventPayload.type === 'response.output_text.done') {
        const aiText = normalizeTranscriptText(eventPayload.transcript || eventPayload.text || '');
        if (aiText && aiText !== lastRealtimeAiTextRef.current) {
          lastRealtimeAiTextRef.current = aiText;
          appendRealtimeTurn('ai', aiText, 'ai-realtime');
        }
      }

      if (eventPayload.type === 'conversation.item.input_audio_transcription.completed') {
        const candidateText = normalizeTranscriptText(eventPayload.transcript || '');
        if (candidateText && candidateText !== lastRealtimeCandidateTextRef.current) {
          lastRealtimeCandidateTextRef.current = candidateText;
          appendRealtimeTurn('candidate', candidateText, 'candidate-realtime');
        }
      }
    },
    [appendRealtimeTurn],
  );

  const exitFullscreenSafely = useCallback(async () => {
    if (document.fullscreenElement && document.exitFullscreen) {
      try {
        await document.exitFullscreen();
      } catch (_error) {
        // no-op
      }
    }
  }, []);

  const sendRealtimeFollowupPrompt = useCallback(() => {
    const channel = rtcDataChannelRef.current;
    if (!channel || channel.readyState !== 'open') {
      return false;
    }

    const prompt = {
      type: 'response.create',
      response: {
        modalities: ['audio', 'text'],
        instructions:
          'Continue the interview. Ask exactly one concise next question based on the candidate\'s latest response.',
      },
    };

    channel.send(JSON.stringify(prompt));
    return true;
  }, []);

  const startRealtimeTransport = useCallback(async () => {
    if (realtimeInitRef.current) {
      return;
    }
    if (!sessionData?.session?.id || !mediaStreamRef.current) {
      return;
    }

    realtimeInitRef.current = true;
    setRealtimeStatus('connecting');

    try {
      const tokenResponse = await api.post(`/candidate/interview-session/${sessionData.session.id}/realtime-token`);
      const realtimePayload = tokenResponse.data?.realtime;
      const ephemeralKey = realtimePayload?.clientSecret;
      const model = realtimePayload?.model || 'gpt-4o-realtime-preview-2024-12-17';
      if (!ephemeralKey) {
        throw new Error('Realtime token unavailable');
      }

      realtimeModelRef.current = model;
      const peerConnection = new RTCPeerConnection();
      rtcPeerConnectionRef.current = peerConnection;

      mediaStreamRef.current.getAudioTracks().forEach((track) => {
        peerConnection.addTrack(track, mediaStreamRef.current);
      });

      peerConnection.ontrack = (event) => {
        const [remoteStream] = event.streams || [];
        if (remoteAudioRef.current && remoteStream) {
          remoteAudioRef.current.srcObject = remoteStream;
        }
      };

      const dataChannel = peerConnection.createDataChannel('oai-events');
      rtcDataChannelRef.current = dataChannel;

      dataChannel.onopen = () => {
        realtimeConnectedRef.current = true;
        setRealtimeStatus('connected');
        sendRealtimeFollowupPrompt();
      };

      dataChannel.onmessage = (messageEvent) => {
        try {
          const parsed = JSON.parse(messageEvent.data);
          handleRealtimeEvent(parsed);
        } catch (_error) {
          // no-op
        }
      };

      dataChannel.onerror = () => {
        setRealtimeStatus('fallback');
      };

      dataChannel.onclose = () => {
        realtimeConnectedRef.current = false;
        if (!sessionFinalizedRef.current && !terminating && !completing) {
          setRealtimeStatus('fallback');
        }
      };

      const offer = await peerConnection.createOffer();
      await peerConnection.setLocalDescription(offer);

      const sdpResponse = await fetch(`https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`, {
        method: 'POST',
        body: offer.sdp,
        headers: {
          Authorization: `Bearer ${ephemeralKey}`,
          'Content-Type': 'application/sdp',
        },
      });

      if (!sdpResponse.ok) {
        throw new Error('Failed to connect realtime stream');
      }

      const answerSdp = await sdpResponse.text();
      await peerConnection.setRemoteDescription({
        type: 'answer',
        sdp: answerSdp,
      });
    } catch (_error) {
      cleanupRealtimeTransport();
      setRealtimeStatus('fallback');
      toast.error('Realtime AI transport unavailable, using browser voice fallback');
    }
  }, [cleanupRealtimeTransport, completing, handleRealtimeEvent, sendRealtimeFollowupPrompt, sessionData?.session?.id, terminating]);

  const terminateInterview = useCallback(
    async (reason) => {
      if (!sessionData?.session?.id || sessionFinalizedRef.current) {
        return;
      }

      try {
        setTerminating(true);
        sessionFinalizedRef.current = true;
        cleanupRealtimeTransport();

        if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
          mediaRecorderRef.current.stop();
        }
        if (mediaStreamRef.current) {
          mediaStreamRef.current.getTracks().forEach((track) => track.stop());
        }

        await api.post(`/candidate/interview-session/${sessionData.session.id}/terminate`, {
          reason,
          transcript: transcriptSnapshot,
          durationSeconds: elapsedSeconds,
        });
      } catch (_error) {
        // best-effort termination
      } finally {
        clearInterviewLock();
        await exitFullscreenSafely();
        toast.error('Interview terminated due to focus/security policy');
        navigate('/candidate', { replace: true });
      }
    },
    [
      cleanupRealtimeTransport,
      clearInterviewLock,
      elapsedSeconds,
      exitFullscreenSafely,
      navigate,
      sessionData?.session?.id,
      transcriptSnapshot,
    ],
  );

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
          setAiOutputMode(resolveAiOutputMode(sessionCheck.data?.aiOutputMode || DEFAULT_AI_OUTPUT_MODE));
          setInterviewRole(sessionCheck.data?.interviewRole || latestSession?.interview_role || plan?.role || 'General Candidate');
          if (sessionCheck.data?.interviewPlan) {
            setInterviewPlan(sessionCheck.data.interviewPlan);
          }
          setResumeSummary(sessionCheck.data?.resumeSummary || latestSession?.resume_summary || '');
          setHasAcknowledgedNotice(true);
          startInterviewLock(verifiedSession.id);
        }
      } catch (_error) {
        setSessionData(null);
        setHasAcknowledgedNotice(false);
      }
    };

    fetchInterviewContext();
  }, [routeSessionId, startInterviewLock]);

  const startInterviewSession = async () => {
    try {
      setStartingSession(true);
      const response = await api.post('/candidate/interview-session/start', {
        consentGiven: true,
      });

      setSessionData(response.data);
      setAiOutputMode(resolveAiOutputMode(response.data?.aiOutputMode || DEFAULT_AI_OUTPUT_MODE));
      setInterviewRole(response.data?.interviewRole || 'General Candidate');
      setInterviewPlan(response.data?.interviewPlan ?? null);
      setResumeSummary(response.data?.resumeSummary || '');
      setHasAcknowledgedNotice(true);
      if (response.data?.session?.id) {
        startInterviewLock(response.data.session.id);
      }
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

        autosaveQueuedRef.current = false;
        lastAutosavedTranscriptRef.current = '';
        lastRequestedTranscriptVersionRef.current = 0;
        lastAppliedTranscriptVersionRef.current = 0;
        setResponses(questions.map(() => ''));
        setTranscriptTurns([]);
        setConnecting(false);
        toast.success('Live interview room is ready');
      } catch (_error) {
        toast.error('Camera and microphone permission is required for interview');
        navigate('/interview', { replace: true });
      }
    };

    startMedia();

    return () => {
      cleanupRealtimeTransport();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, [cleanupRealtimeTransport, hasAcknowledgedNotice, navigate, questions, sessionData?.session?.id]);

  useEffect(() => {
    if (!hasAcknowledgedNotice || !sessionData?.session?.id) {
      return;
    }

    const requestFullscreen = async () => {
      if (!document.fullscreenElement) {
        try {
          await document.documentElement.requestFullscreen();
        } catch (_error) {
          await terminateInterview('fullscreen_exit');
        }
      }
    };

    requestFullscreen();

    const onFullscreenChange = () => {
      if (!document.fullscreenElement && !completing && !terminating && !sessionFinalizedRef.current) {
        terminateInterview('fullscreen_exit');
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden' && !completing && !terminating && !sessionFinalizedRef.current) {
        terminateInterview('tab_leave');
      }
    };

    const onBeforeUnload = (event) => {
      if (sessionFinalizedRef.current || completing || terminating) {
        return;
      }
      event.preventDefault();
      event.returnValue = '';
    };

    document.addEventListener('fullscreenchange', onFullscreenChange);
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('beforeunload', onBeforeUnload);

    return () => {
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('beforeunload', onBeforeUnload);
    };
  }, [completing, hasAcknowledgedNotice, sessionData?.session?.id, terminateInterview, terminating]);

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
    if (connecting || !hasAcknowledgedNotice || !sessionData?.session?.id || !mediaStreamRef.current) {
      return;
    }

    if (aiOutputMode !== 'openai_stream') {
      cleanupRealtimeTransport();
      setRealtimeStatus('idle');
      return;
    }

    void startRealtimeTransport();
  }, [
    aiOutputMode,
    cleanupRealtimeTransport,
    connecting,
    hasAcknowledgedNotice,
    sessionData?.session?.id,
    startRealtimeTransport,
  ]);

  useEffect(() => {
    if (!activeQuestion) {
      return;
    }

    const scriptedFallbackMode = aiOutputMode !== 'openai_stream' || realtimeStatus === 'fallback';
    if (!scriptedFallbackMode) {
      return;
    }

    // Phase 2: browser speech acts as resilient fallback while openai_stream transport is wired.
    if (window.speechSynthesis) {
      const utterance = new SpeechSynthesisUtterance(activeQuestion);
      utterance.rate = 1;
      utterance.pitch = 1;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
    }

    setTranscriptTurns((prev) => {
      const aiTurnId = `ai-${activeQuestionIndex}`;
      const existing = prev.find((turn) => turn.id === aiTurnId);
      if (existing) {
        return prev;
      }
      return [
        ...prev,
        {
          id: aiTurnId,
          speaker: 'ai',
          text: activeQuestion,
          timestamp: new Date().toISOString(),
        },
      ];
    });
  }, [activeQuestion, aiOutputMode, realtimeStatus]);

  const onAnswerChange = (value) => {
    setResponses((prev) => {
      const next = [...prev];
      next[activeQuestionIndex] = value;
      return next;
    });

    setTranscriptTurns((prev) => {
      const candidateTurnId = `candidate-${activeQuestionIndex}`;
      const idx = prev.findIndex((turn) => turn.id === candidateTurnId);
      const nextTurn = {
        id: candidateTurnId,
        speaker: 'candidate',
        text: value,
        timestamp: new Date().toISOString(),
      };

      if (idx === -1) {
        return [...prev, nextTurn];
      }

      const copy = [...prev];
      copy[idx] = nextTurn;
      return copy;
    });
  };

  useEffect(() => {
    if (!sessionData?.session?.id || !hasAcknowledgedNotice || sessionFinalizedRef.current) {
      return;
    }

    const attemptAutosave = async () => {
      if (autosaveInFlightRef.current) {
        autosaveQueuedRef.current = true;
        return;
      }

      const transcript = buildTranscriptFromTurns(transcriptTurnsRef.current);
      if (!transcript || transcript === lastAutosavedTranscriptRef.current) {
        return;
      }

      const nextTranscriptVersion = lastRequestedTranscriptVersionRef.current + 1;
      lastRequestedTranscriptVersionRef.current = nextTranscriptVersion;

      autosaveInFlightRef.current = true;
      setAutosavingTranscript(true);
      try {
        const response = await api.patch(`/candidate/interview-session/${sessionData.session.id}/transcript`, {
          transcript,
          transcriptTurns: transcriptTurnsRef.current,
          transcriptVersion: nextTranscriptVersion,
        });

        const serverVersion = response.data?.transcriptVersion;
        const applied = response.data?.applied !== false;

        if (Number.isInteger(serverVersion)) {
          lastAppliedTranscriptVersionRef.current = serverVersion;
          if (serverVersion > lastRequestedTranscriptVersionRef.current) {
            lastRequestedTranscriptVersionRef.current = serverVersion;
          }
        } else if (applied) {
          lastAppliedTranscriptVersionRef.current = nextTranscriptVersion;
        }

        if (applied) {
          lastAutosavedTranscriptRef.current = transcript;
        }
      } catch (_error) {
        // Keep recording even if autosave misses a tick.
      } finally {
        autosaveInFlightRef.current = false;
        setAutosavingTranscript(false);

        if (autosaveQueuedRef.current && !sessionFinalizedRef.current) {
          autosaveQueuedRef.current = false;
          window.setTimeout(() => {
            void attemptAutosave();
          }, 250);
        }
      }
    };

    const intervalId = window.setInterval(() => {
      void attemptAutosave();
    }, 5000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [hasAcknowledgedNotice, sessionData?.session?.id]);

  useEffect(() => {
    return () => {
      if (sessionData?.session?.id && !sessionFinalizedRef.current && !completing && !terminating) {
        terminateInterview('route_leave');
      }
    };
  }, [completing, sessionData?.session?.id, terminateInterview, terminating]);

  const onNextQuestion = () => {
    if (aiOutputMode === 'openai_stream' && realtimeConnectedRef.current) {
      const sent = sendRealtimeFollowupPrompt();
      if (!sent) {
        toast.error('Realtime interviewer is reconnecting. Please try again.');
      }
      return;
    }

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
      cleanupRealtimeTransport();

      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }

      await new Promise((resolve) => window.setTimeout(resolve, 300));

      const recordingBlob = new Blob(recordedChunksRef.current, { type: 'video/webm' });
      const sessionId = sessionData.session.id;
      const uploadResult = await uploadBlobToSignedUrl(recordingBlob, sessionId, 'video', 'webm');
      const storedVideoPath = uploadResult.path;
      const videoUploadNonce = uploadResult.uploadNonce;

      const fallbackTranscriptText = questions
        .map((question, index) => {
          const answer = responses[index] || '(no response captured)';
          return `Q${index + 1}: ${question}\nA${index + 1}: ${answer}`;
        })
        .join('\n\n');
      const transcriptText = transcriptSnapshot || fallbackTranscriptText;

      await api.post(`/candidate/interview-session/${sessionId}/complete`, {
        transcript: transcriptText,
        durationSeconds: elapsedSeconds,
        videoPath: storedVideoPath,
        videoUploadNonce,
        videoUrl: null,
        scorePayload: {
          role: sessionData?.interviewRole,
          transcriptTurns,
        },
      });

      sessionFinalizedRef.current = true;
      clearInterviewLock();
      await exitFullscreenSafely();
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
        <p className="mt-1 text-xs text-amber-700">
          Focus mode is active. Leaving fullscreen, changing tabs, or navigating away will terminate the interview.
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
          <p className="text-xs text-slate-500">
            AI output mode: {aiOutputMode === 'openai_stream' ? 'openai_stream (browser voice fallback active)' : 'browser_tts'}
          </p>
          {aiOutputMode === 'openai_stream' ? (
            <p className="mt-1 text-xs text-indigo-700">
              Realtime transport: {realtimeStatus === 'connected' ? 'connected' : realtimeStatus === 'connecting' ? 'connecting...' : 'fallback'}
            </p>
          ) : null}
          <audio ref={remoteAudioRef} autoPlay playsInline className="hidden" />
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

          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Live transcript</p>
              {autosavingTranscript ? <p className="text-xs text-teal-700">Autosaving...</p> : null}
            </div>
            <div className="max-h-40 overflow-y-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
              {transcriptTurns.length ? (
                transcriptTurns.map((turn) => (
                  <p key={turn.id} className="mb-1 last:mb-0">
                    <span className="font-semibold">{turn.speaker === 'ai' ? 'AI' : 'Candidate'}:</span> {turn.text || '(typing...)'}
                  </p>
                ))
              ) : (
                <p>No transcript entries yet.</p>
              )}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={onNextQuestion}
              disabled={
                aiOutputMode === 'openai_stream'
                  ? realtimeStatus === 'connecting'
                  : activeQuestionIndex >= questions.length - 1
              }
            >
              {aiOutputMode === 'openai_stream' ? 'Ask Next Follow-up' : 'Next Question'}
            </Button>
            <Button onClick={onEndInterview} disabled={connecting || completing || terminating} className="gap-1.5">
              <PhoneOff size={16} /> {completing ? 'Submitting...' : 'End Interview'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
