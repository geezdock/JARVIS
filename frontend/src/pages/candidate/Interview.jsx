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
const DEFAULT_MAX_REALTIME_QUESTIONS = 6;
const VOICE_SILENCE_AUTO_STOP_MS = 2500;

const normalizeTranscriptText = (value) => (typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '');

const parseRealtimeQuestionOrdinal = (text) => {
  const normalized = normalizeTranscriptText(text);
  if (!normalized) {
    return null;
  }

  const prefixedMatch = normalized.match(/^Q\s*(\d+)\s*\//i);
  if (prefixedMatch) {
    return Number(prefixedMatch[1]);
  }

  if (normalized.endsWith('?')) {
    return -1;
  }

  return null;
};

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

  const uploadResponse = await fetch(signedUrl, {
    method: 'PUT',
    headers: {
      'Content-Type': blob.type || 'video/webm',
      'x-upsert': 'false',
    },
    body: blob,
  });

  if (!uploadResponse.ok) {
    throw new Error('Failed to upload interview recording');
  }

  return {
    path,
    uploadNonce,
  };
};

export default function Interview() {
  const navigate = useNavigate();
  const location = useLocation();
  const { interviewLock, startInterviewLock, clearInterviewLock } = useAuth();
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
  const [questionsAsked, setQuestionsAsked] = useState(0);
  const [awaitingCandidateReply, setAwaitingCandidateReply] = useState(false);
  const [interviewCompleteReason, setInterviewCompleteReason] = useState('');
  const [loadingGroqQuestion, setLoadingGroqQuestion] = useState(false);
  const [speechRecognitionSupported, setSpeechRecognitionSupported] = useState(false);
  const [capturingVoiceAnswer, setCapturingVoiceAnswer] = useState(false);

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
  const questionsAskedRef = useRef(0);
  const awaitingCandidateReplyRef = useRef(false);
  const autoCompletingRef = useRef(false);
  const lastStartInterviewErrorRef = useRef({ message: '', at: 0 });
  const startInterviewProviderErrorShownRef = useRef(false);
  const speechRecognitionRef = useRef(null);
  const speechFinalBufferRef = useRef('');
  const speechSilenceTimerRef = useRef(null);

  const questions = useMemo(() => interviewPlan?.questions ?? [], [interviewPlan]);
  const maxRealtimeQuestions = useMemo(() => {
    const configured = sessionData?.interviewPlan?.realtime?.maxQuestions;
    if (Number.isInteger(configured) && configured > 0) {
      return configured;
    }
    return DEFAULT_MAX_REALTIME_QUESTIONS;
  }, [sessionData?.interviewPlan?.realtime?.maxQuestions]);
  const activeQuestion = questions[activeQuestionIndex] ?? null;
  const routeSessionId = location.state?.sessionData?.session?.id || null;
  const isLiveInterviewRoute = location.pathname === '/interview/live';
  const transcriptSnapshot = useMemo(() => buildTranscriptFromTurns(transcriptTurns), [transcriptTurns]);
  const useGroqVoiceMode = useMemo(() => {
    const voiceProvider = sessionData?.interviewPlan?.realtime?.voiceProvider;
    return aiOutputMode !== 'openai_stream' && voiceProvider === 'groq_browser';
  }, [aiOutputMode, sessionData?.interviewPlan?.realtime?.voiceProvider]);

  const speakText = useCallback((text) => {
    const normalized = normalizeTranscriptText(text);
    if (!normalized || !window.speechSynthesis) {
      return;
    }
    const utterance = new SpeechSynthesisUtterance(normalized);
    utterance.rate = 1;
    utterance.pitch = 1;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }, []);

  const clearSpeechSilenceTimer = useCallback(() => {
    if (speechSilenceTimerRef.current) {
      window.clearTimeout(speechSilenceTimerRef.current);
      speechSilenceTimerRef.current = null;
    }
  }, []);

  const stopVoiceAnswerCapture = useCallback((reason = 'manual') => {
    clearSpeechSilenceTimer();

    if (speechRecognitionRef.current) {
      try {
        speechRecognitionRef.current.stop();
      } catch (_error) {
        // no-op
      }
    }
    setCapturingVoiceAnswer(false);

    if (reason === 'silence') {
      toast('Voice capture paused after silence. You can start again if needed.');
    }
  }, [clearSpeechSilenceTimer]);

  useEffect(() => {
    transcriptTurnsRef.current = transcriptTurns;
  }, [transcriptTurns]);

  useEffect(() => {
    questionsAskedRef.current = questionsAsked;
  }, [questionsAsked]);

  useEffect(() => {
    awaitingCandidateReplyRef.current = awaitingCandidateReply;
  }, [awaitingCandidateReply]);

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    setSpeechRecognitionSupported(typeof SpeechRecognition === 'function');

    return () => {
      clearSpeechSilenceTimer();
      if (speechRecognitionRef.current) {
        try {
          speechRecognitionRef.current.stop();
        } catch (_error) {
          // no-op
        }
      }
    };
  }, [clearSpeechSilenceTimer]);

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

  const exitFullscreenSafely = useCallback(async () => {
    if (document.fullscreenElement && document.exitFullscreen) {
      try {
        await document.exitFullscreen();
      } catch (_error) {
        // no-op
      }
    }
  }, []);

  const buildRealtimeTurnPrompt = useCallback(
    (phase = 'followup') => {
      const jobContext = sessionData?.interviewPlan?.job_context || {};
      const flowTopics = Array.isArray(sessionData?.interviewPlan?.flow) ? sessionData.interviewPlan.flow.join(', ') : '';
      const requiredSkills = Array.isArray(jobContext?.required_skills) ? jobContext.required_skills.join(', ') : '';
      const responsibilities = Array.isArray(jobContext?.key_responsibilities) ? jobContext.key_responsibilities.join(', ') : '';
      const nextQuestionNumber = Math.min(maxRealtimeQuestions, questionsAskedRef.current + 1);

      return [
        `You are conducting a one-on-one live interview for role: ${sessionData?.interviewRole || interviewRole || 'General Candidate'}.`,
        `Ask exactly one concise question now, prefixed as Q${nextQuestionNumber}/${maxRealtimeQuestions}:.`,
        'Do not provide hints or model answers. Do not ask compound questions.',
        `Use resume context: ${resumeSummary || 'No resume summary available.'}`,
        `Use flow topics when relevant: ${flowTopics || 'General role fit and problem solving.'}`,
        `Use JD required skills when relevant: ${requiredSkills || 'Not provided.'}`,
        `Use JD responsibilities when relevant: ${responsibilities || 'Not provided.'}`,
        'Avoid repeating prior question topics from transcript history.',
        phase === 'initial' ? 'This is the first question of the interview.' : 'This is the next follow-up question based on the latest candidate response.',
      ].join(' ');
    },
    [interviewRole, maxRealtimeQuestions, resumeSummary, sessionData?.interviewPlan?.flow, sessionData?.interviewPlan?.job_context, sessionData?.interviewRole],
  );

  const sendRealtimeFollowupPrompt = useCallback((phase = 'followup') => {
    const channel = rtcDataChannelRef.current;
    if (!channel || channel.readyState !== 'open') {
      return false;
    }

    const prompt = {
      type: 'response.create',
      response: {
        modalities: ['audio', 'text'],
        instructions: buildRealtimeTurnPrompt(phase),
      },
    };

    channel.send(JSON.stringify(prompt));
    return true;
  }, [buildRealtimeTurnPrompt]);

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

          if (aiText.includes('INTERVIEW_COMPLETE')) {
            if (!autoCompletingRef.current) {
              autoCompletingRef.current = true;
              setInterviewCompleteReason('question_limit_reached');
            }
            return;
          }

          const parsedQuestionOrdinal = parseRealtimeQuestionOrdinal(aiText);
          if (parsedQuestionOrdinal !== null) {
            setAwaitingCandidateReply(true);
            if (parsedQuestionOrdinal > 0) {
              setQuestionsAsked((prev) => Math.max(prev, parsedQuestionOrdinal));
            } else {
              setQuestionsAsked((prev) => prev + 1);
            }
          }
        }
      }

      if (eventPayload.type === 'conversation.item.input_audio_transcription.completed') {
        const candidateText = normalizeTranscriptText(eventPayload.transcript || '');
        if (candidateText && candidateText !== lastRealtimeCandidateTextRef.current) {
          lastRealtimeCandidateTextRef.current = candidateText;
          appendRealtimeTurn('candidate', candidateText, 'candidate-realtime');

          if (!awaitingCandidateReplyRef.current) {
            return;
          }

          setAwaitingCandidateReply(false);

          if (questionsAskedRef.current >= maxRealtimeQuestions) {
            if (!autoCompletingRef.current) {
              autoCompletingRef.current = true;
              setInterviewCompleteReason('question_limit_reached');
            }
            return;
          }

          window.setTimeout(() => {
            sendRealtimeFollowupPrompt('followup');
          }, 350);
        }
      }
    },
    [appendRealtimeTurn, maxRealtimeQuestions, sendRealtimeFollowupPrompt],
  );

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
      const tokenMaxQuestions = realtimePayload?.maxQuestions;
      if (!ephemeralKey) {
        throw new Error('Realtime token unavailable');
      }

      if (Number.isInteger(tokenMaxQuestions) && tokenMaxQuestions > 0) {
        setSessionData((prev) => {
          if (!prev) {
            return prev;
          }
          return {
            ...prev,
            interviewPlan: {
              ...(prev.interviewPlan || {}),
              realtime: {
                ...((prev.interviewPlan || {}).realtime || {}),
                maxQuestions: tokenMaxQuestions,
              },
            },
          };
        });
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
        sendRealtimeFollowupPrompt('initial');
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

  const requestGroqNextQuestion = useCallback(async () => {
    if (!sessionData?.session?.id || loadingGroqQuestion || sessionFinalizedRef.current) {
      return;
    }

    try {
      setLoadingGroqQuestion(true);
      const response = await api.post(`/candidate/interview-session/${sessionData.session.id}/groq-next-question`, {
        transcriptTurns: transcriptTurnsRef.current,
        questionsAsked: questionsAskedRef.current,
      });

      const payload = response.data || {};
      if (payload.completed) {
        if (!autoCompletingRef.current) {
          autoCompletingRef.current = true;
          setInterviewCompleteReason('question_limit_reached');
        }
        return;
      }

      const questionText = normalizeTranscriptText(payload.question || '');
      if (!questionText) {
        throw new Error('Groq interviewer returned an empty question');
      }

      const questionNumber = Number.isInteger(payload.questionNumber)
        ? payload.questionNumber
        : questionsAskedRef.current + 1;

      setQuestionsAsked(questionNumber);
      setAwaitingCandidateReply(true);
      appendRealtimeTurn('ai', questionText, `ai-groq-${questionNumber}`);
      speakText(questionText);
    } catch (error) {
      toast.error(error?.message || 'Unable to get next Groq interview question');
    } finally {
      setLoadingGroqQuestion(false);
    }
  }, [appendRealtimeTurn, loadingGroqQuestion, sessionData?.session?.id, speakText]);

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
        const terminationMessage =
          reason === 'route_leave'
            ? 'Interview session ended while leaving the interview page.'
            : 'Interview session terminated.';
        toast.error(terminationMessage);
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
          // Keep consent gate state as-is to avoid bouncing back while live room initializes.
          startInterviewLock(verifiedSession.id);
        } else {
          // Recover from stale lock/session storage state.
          clearInterviewLock();
          setSessionData(null);
          setHasAcknowledgedNotice(false);
        }
      } catch (_error) {
        setSessionData(null);
        setHasAcknowledgedNotice(false);
        clearInterviewLock();
      }
    };

    fetchInterviewContext();
  }, [clearInterviewLock, routeSessionId, startInterviewLock]);

  useEffect(() => {
    // If lock exists but there is no current session, reset stale state.
    if (interviewLock?.active && !sessionData?.session?.id && !startingSession) {
      clearInterviewLock();
    }
  }, [clearInterviewLock, interviewLock?.active, sessionData?.session?.id, startingSession]);

  const startInterviewSession = async () => {
    try {
      setStartingSession(true);
      lastStartInterviewErrorRef.current = { message: '', at: 0 };
      setConnecting(true);
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
      const message = error?.message || 'Unable to start interview session right now';
      const now = Date.now();
      const isDuplicateError =
        lastStartInterviewErrorRef.current.message === message && now - lastStartInterviewErrorRef.current.at < 5000;

      if (isDuplicateError) {
        return;
      }

      lastStartInterviewErrorRef.current = { message, at: now };

      if (
        message.includes('Scoring provider unavailable') ||
        message.includes('Scoring provider is not configured') ||
        message.includes('No configured LLM provider found') ||
        message.includes('408 Timeout')
      ) {
        if (startInterviewProviderErrorShownRef.current) {
          return;
        }

        startInterviewProviderErrorShownRef.current = true;
        toast.error('Interview services are still starting up. Please try again shortly.');
        return;
      }

      if (message.includes('already exists for this application stage')) {
        toast('Interview already exists for this stage. Redirecting to interview schedule.');
        setSessionData(null);
        setHasAcknowledgedNotice(false);
        clearInterviewLock();
        navigate('/interview', { replace: true });
        return;
      }
      toast.error(message);
    } finally {
      setStartingSession(false);
    }
  };

  const continueToInterview = async () => {
    if (sessionData?.session?.id) {
      setHasAcknowledgedNotice(true);
      return;
    }

    await startInterviewSession();
  };

  useEffect(() => {
    if (!isLiveInterviewRoute) {
      return;
    }

    if (!hasAcknowledgedNotice) {
      return;
    }

    if (!sessionData?.session?.id) {
      return;
    }

    let canceled = false;

    const startMedia = async () => {
      try {
        const existingStream = mediaStreamRef.current;
        if (existingStream && existingStream.getTracks().some((track) => track.readyState === 'live')) {
          if (videoRef.current) {
            videoRef.current.srcObject = existingStream;
          }
          setConnecting(false);
          return;
        }

        const stream = await navigator.mediaDevices.getUserMedia({
          video: true,
          audio: true,
        });

        if (canceled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

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
        questionsAskedRef.current = 0;
        awaitingCandidateReplyRef.current = false;
        autoCompletingRef.current = false;
        speechFinalBufferRef.current = '';
        stopVoiceAnswerCapture();
        setQuestionsAsked(0);
        setAwaitingCandidateReply(false);
        setInterviewCompleteReason('');
        setResponses((prev) => (prev.length ? prev : questions.map(() => '')));
        setTranscriptTurns([]);
        setConnecting(false);
        toast.success('Live interview room is ready');
      } catch (_error) {
        if (canceled) {
          return;
        }
        toast.error('Camera and microphone permission is required for interview');
        setSessionData(null);
        setHasAcknowledgedNotice(false);
        clearInterviewLock();
        navigate('/interview', { replace: true });
      }
    };

    startMedia();

    return () => {
      canceled = true;
      cleanupRealtimeTransport();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, [cleanupRealtimeTransport, clearInterviewLock, hasAcknowledgedNotice, isLiveInterviewRoute, navigate, sessionData?.session?.id, stopVoiceAnswerCapture]);

  useEffect(() => {
    if (!useGroqVoiceMode && capturingVoiceAnswer) {
      stopVoiceAnswerCapture();
    }
  }, [capturingVoiceAnswer, stopVoiceAnswerCapture, useGroqVoiceMode]);

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
    if (!hasAcknowledgedNotice || connecting || !sessionData?.session?.id) {
      return;
    }

    if (useGroqVoiceMode) {
      if (questionsAskedRef.current === 0 && !loadingGroqQuestion) {
        void requestGroqNextQuestion();
      }
      return;
    }

    if (!activeQuestion) {
      return;
    }

    const scriptedFallbackMode = aiOutputMode !== 'openai_stream' || realtimeStatus === 'fallback';
    if (!scriptedFallbackMode) {
      return;
    }

    // Phase 2: browser speech acts as resilient fallback while openai_stream transport is wired.
    speakText(activeQuestion);

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
  }, [
    activeQuestion,
    aiOutputMode,
    connecting,
    hasAcknowledgedNotice,
    loadingGroqQuestion,
    realtimeStatus,
    requestGroqNextQuestion,
    sessionData?.session?.id,
    speakText,
    useGroqVoiceMode,
  ]);

  const onAnswerChange = useCallback((value) => {
    const responseIndex = useGroqVoiceMode ? Math.max(questionsAsked - 1, 0) : activeQuestionIndex;

    setResponses((prev) => {
      const next = [...prev];
      next[responseIndex] = value;
      return next;
    });

    setTranscriptTurns((prev) => {
      const candidateTurnId = useGroqVoiceMode ? `candidate-groq-${questionsAsked}` : `candidate-${activeQuestionIndex}`;
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
  }, [activeQuestionIndex, questionsAsked, useGroqVoiceMode]);

  const startVoiceAnswerCapture = useCallback(() => {
    if (!useGroqVoiceMode) {
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (typeof SpeechRecognition !== 'function') {
      toast.error('Voice recognition is not supported in this browser.');
      return;
    }

    const responseIndex = Math.max(questionsAsked - 1, 0);
    const existingText = normalizeTranscriptText(responses[responseIndex] || '');
    speechFinalBufferRef.current = existingText;

    const recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.continuous = true;
    recognition.interimResults = true;

    const resetSilenceAutoStop = () => {
      clearSpeechSilenceTimer();
      speechSilenceTimerRef.current = window.setTimeout(() => {
        stopVoiceAnswerCapture('silence');
      }, VOICE_SILENCE_AUTO_STOP_MS);
    };

    recognition.onresult = (event) => {
      let interimText = '';
      let finalChunk = '';

      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const transcript = normalizeTranscriptText(event.results[index][0]?.transcript || '');
        if (!transcript) {
          continue;
        }
        if (event.results[index].isFinal) {
          finalChunk = `${finalChunk} ${transcript}`.trim();
        } else {
          interimText = `${interimText} ${transcript}`.trim();
        }
      }

      if (finalChunk) {
        speechFinalBufferRef.current = normalizeTranscriptText(`${speechFinalBufferRef.current} ${finalChunk}`);
      }

      const mergedText = normalizeTranscriptText(`${speechFinalBufferRef.current} ${interimText}`);
      if (mergedText) {
        onAnswerChange(mergedText);
        resetSilenceAutoStop();
      }
    };

    recognition.onerror = () => {
      clearSpeechSilenceTimer();
      setCapturingVoiceAnswer(false);
    };

    recognition.onend = () => {
      clearSpeechSilenceTimer();
      setCapturingVoiceAnswer(false);
      speechRecognitionRef.current = null;
    };

    try {
      speechRecognitionRef.current = recognition;
      recognition.start();
      resetSilenceAutoStop();
      setCapturingVoiceAnswer(true);
    } catch (_error) {
      toast.error('Unable to start voice capture right now.');
      setCapturingVoiceAnswer(false);
    }
  }, [
    clearSpeechSilenceTimer,
    onAnswerChange,
    questionsAsked,
    responses,
    stopVoiceAnswerCapture,
    useGroqVoiceMode,
  ]);

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

  const onNextQuestion = () => {
    if (useGroqVoiceMode) {
      if (capturingVoiceAnswer) {
        stopVoiceAnswerCapture();
      }

      if (questionsAsked >= maxRealtimeQuestions) {
        setInterviewCompleteReason('question_limit_reached');
        return;
      }

      const responseIndex = Math.max(questionsAsked - 1, 0);
      const typedAnswer = normalizeTranscriptText(responses[responseIndex] || '');
      if (!typedAnswer) {
        toast.error('Please provide your answer before moving to the next question.');
        return;
      }

      setAwaitingCandidateReply(false);
      void requestGroqNextQuestion();
      return;
    }

    if (aiOutputMode === 'openai_stream' && realtimeConnectedRef.current) {
      const sent = sendRealtimeFollowupPrompt('followup');
      if (!sent) {
        toast.error('Realtime interviewer is reconnecting. Please try again.');
      }
      return;
    }

    if (activeQuestionIndex < questions.length - 1) {
      setActiveQuestionIndex((prev) => prev + 1);
    }
  };

  const onEndInterview = useCallback(async (completionReason = 'manual_end') => {
    if (!sessionData?.session?.id) {
      toast.error('Interview session context is missing');
      return;
    }

    try {
      setCompleting(true);
      cleanupRealtimeTransport();
      if (capturingVoiceAnswer) {
        stopVoiceAnswerCapture();
      }

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
          completionReason,
          questionsAsked,
          maxQuestions: maxRealtimeQuestions,
          transcriptTurns,
        },
      });

      sessionFinalizedRef.current = true;
      clearInterviewLock();
      await exitFullscreenSafely();
      toast.success(
        completionReason === 'question_limit_reached'
          ? 'Interview completed after the planned number of questions'
          : 'Interview completed and submitted',
      );
      navigate('/candidate', { replace: true });
    } catch (error) {
      toast.error(error.message || 'Unable to complete interview session');
    } finally {
      setCompleting(false);
    }
  }, [
    cleanupRealtimeTransport,
    clearInterviewLock,
    elapsedSeconds,
    exitFullscreenSafely,
    maxRealtimeQuestions,
    navigate,
    questions,
    questionsAsked,
    responses,
    sessionData?.interviewRole,
    sessionData?.session?.id,
    capturingVoiceAnswer,
    stopVoiceAnswerCapture,
    transcriptSnapshot,
    transcriptTurns,
  ]);

  useEffect(() => {
    if (!interviewCompleteReason || sessionFinalizedRef.current || completing || terminating) {
      return;
    }

    if (interviewCompleteReason === 'question_limit_reached') {
      void onEndInterview('question_limit_reached');
    }
  }, [completing, interviewCompleteReason, onEndInterview, terminating]);

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
          <Button onClick={continueToInterview} disabled={startingSession}>
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
          <Button onClick={continueToInterview} disabled={startingSession}>
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
          <p className="text-xs text-slate-500">
            AI output mode: {aiOutputMode === 'openai_stream' ? 'openai_stream (browser voice fallback active)' : 'browser_tts'}
          </p>
          {useGroqVoiceMode ? (
            <p className="mt-1 text-xs text-emerald-700">Groq interviewer enabled with browser voice playback.</p>
          ) : null}
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

          {(aiOutputMode !== 'openai_stream' || realtimeStatus === 'fallback') && activeQuestion && (
            <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {useGroqVoiceMode ? `Question ${questionsAsked || 1} of ${maxRealtimeQuestions}` : `Question ${activeQuestionIndex + 1} of ${questions.length}`}
              </p>
              <p className="mt-2 text-sm font-semibold text-slate-900">
                {useGroqVoiceMode ? (transcriptTurns.filter((turn) => turn.speaker === 'ai').slice(-1)[0]?.text || 'Loading Groq question...') : activeQuestion}
              </p>
              <textarea
                className="mt-3 h-24 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-teal-500"
                value={responses[useGroqVoiceMode ? Math.max(questionsAsked - 1, 0) : activeQuestionIndex] || ''}
                onChange={(event) => onAnswerChange(event.target.value)}
                placeholder="Type candidate response transcript notes here..."
              />
              {useGroqVoiceMode ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={capturingVoiceAnswer ? stopVoiceAnswerCapture : startVoiceAnswerCapture}
                    disabled={!speechRecognitionSupported}
                    className="gap-1.5"
                  >
                    <Mic size={16} />
                    {capturingVoiceAnswer ? 'Stop Voice Answer' : 'Start Voice Answer'}
                  </Button>
                  {!speechRecognitionSupported ? (
                    <p className="text-xs text-amber-700">Speech recognition not available in this browser.</p>
                  ) : (
                    <p className="text-xs text-slate-500">Voice capture auto-stops after about 2.5s of silence.</p>
                  )}
                </div>
              ) : null}
            </div>
          )}

          {(aiOutputMode === 'openai_stream' && realtimeStatus !== 'fallback') || useGroqVoiceMode ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {useGroqVoiceMode ? 'Groq interview progress' : 'Realtime interview progress'}
              </p>
              <p className="mt-2 text-sm text-slate-900">
                Questions asked: <span className="font-semibold">{questionsAsked}</span> / {maxRealtimeQuestions}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                {awaitingCandidateReply
                  ? 'AI is waiting for your response.'
                  : useGroqVoiceMode
                    ? 'Click next to fetch the next Groq question.'
                    : 'AI will ask the next question automatically.'}
              </p>
            </div>
          ) : null}

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
                  ? realtimeStatus === 'connecting' || questionsAsked >= maxRealtimeQuestions
                  : useGroqVoiceMode
                    ? loadingGroqQuestion || questionsAsked >= maxRealtimeQuestions
                    : activeQuestionIndex >= questions.length - 1
              }
            >
              {aiOutputMode === 'openai_stream'
                ? 'Force Next Follow-up'
                : useGroqVoiceMode
                  ? (loadingGroqQuestion ? 'Loading...' : 'Next Groq Question')
                  : 'Next Question'}
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
