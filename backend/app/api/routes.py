from datetime import datetime, UTC, timedelta
from concurrent.futures import ThreadPoolExecutor
import io
import inspect
import json
import re
import secrets
import time
from collections import Counter
from typing import Any
from uuid import UUID
import threading
from urllib.parse import quote
from urllib import error, request

from fastapi import APIRouter, HTTPException, Request, Query, status
from pydantic import BaseModel
from pypdf import PdfReader

from app.config import settings
from app.llm.providers import LLMProviderError, get_llm_provider, get_llm_provider_by_name, get_llm_provider_chain

router = APIRouter()


class ProfileUploadPayload(BaseModel):
    filename: str
    size: int
    type: str
    filePath: str | None = None
    fileUrl: str | None = None
    targetRole: str | None = None
    submittedAt: str


class JobSpecificationPayload(BaseModel):
    filename: str
    size: int
    type: str
    filePath: str | None = None
    fileUrl: str | None = None
    submittedAt: str


class InterviewSlotPayload(BaseModel):
    slotTime: str


class SignedUploadPayload(BaseModel):
    path: str


class SignedInterviewUploadPayload(BaseModel):
    sessionId: str
    fileType: str
    extension: str | None = None


class ResumeAnalysisPayload(BaseModel):
    force: bool = False
    runInBackground: bool = False


class AdminCandidateStagePayload(BaseModel):
    stage: str


class AdminBulkCandidateStagePayload(BaseModel):
    candidateIds: list[str]
    stage: str
    runInBackground: bool = False


class AdminInterviewRolePayload(BaseModel):
    targetRole: str | None = None
    adminOverrideRole: str | None = None


class InterviewSessionStartPayload(BaseModel):
    consentGiven: bool = False


class InterviewSessionCompletePayload(BaseModel):
    transcript: str | None = None
    scorePayload: dict[str, Any] | None = None
    durationSeconds: int | None = None
    audioPath: str | None = None
    audioUrl: str | None = None
    audioUploadNonce: str | None = None
    videoPath: str | None = None
    videoUrl: str | None = None
    videoUploadNonce: str | None = None


class InterviewSessionTranscriptPatchPayload(BaseModel):
    transcript: str | None = None
    transcriptTurns: list[dict[str, Any]] | None = None
    transcriptVersion: int | None = None


class InterviewSessionTerminatePayload(BaseModel):
    reason: str
    transcript: str | None = None
    durationSeconds: int | None = None


class InterviewSessionNextQuestionPayload(BaseModel):
    transcriptTurns: list[dict[str, Any]] | None = None
    questionsAsked: int = 0


class AdminHiringOutcomePayload(BaseModel):
    outcome: str
    retentionDays: int = 30


class AdminCleanupArtifactsPayload(BaseModel):
    limit: int = 100
    runInBackground: bool = False


class SupabaseError(RuntimeError):
    pass


def _is_supabase_network_error(raw_message: str | None) -> bool:
    normalized = (raw_message or "").lower()
    return any(
        token in normalized
        for token in [
            "supabase_network_error",
            "timed out",
            "timeout",
            "forcibly closed",
            "connection reset",
            "temporary failure",
            "name or service not known",
            "network is unreachable",
            "ssl",
        ]
    )


INTERVIEW_ROLES = [
    "Frontend Developer",
    "Backend Developer",
    "Data Analyst",
    "Machine Learning Engineer",
    "Product Manager",
    "QA Engineer",
]

VALID_CANDIDATE_STAGES = [
    "profile_pending",
    "under_review",
    "interview_scheduled",
    "interview_completed",
    "offer_extended",
    "rejected",
]

BACKGROUND_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=4)
BACKGROUND_JOB_LOCK = threading.Lock()
BACKGROUND_JOBS: dict[str, dict[str, Any]] = {}


def _normalize_role_value(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _infer_interview_role_from_resume_text(extracted_text: str) -> str | None:
    normalized_text = re.sub(r"\s+", " ", (extracted_text or "").lower())
    if not normalized_text:
        return None

    role_keywords: list[tuple[str, list[str]]] = [
        ("Frontend Developer", ["react", "frontend", "javascript", "typescript", "css", "ui"]),
        ("Backend Developer", ["fastapi", "django", "flask", "backend", "api", "postgres", "sql"]),
        ("Data Analyst", ["sql", "analytics", "dashboard", "power bi", "tableau", "excel"]),
        ("Machine Learning Engineer", ["machine learning", "ml", "tensorflow", "pytorch", "model", "sklearn"]),
        ("Product Manager", ["product", "roadmap", "stakeholder", "prioritization", "discovery"]),
        ("QA Engineer", ["qa", "testing", "test case", "automation", "selenium", "cypress"]),
    ]

    best_role = None
    best_hits = 0
    for role, keywords in role_keywords:
        hits = sum(1 for keyword in keywords if keyword in normalized_text)
        if hits > best_hits:
            best_hits = hits
            best_role = role

    return best_role if best_hits > 0 else None


def _resolve_interview_role(candidate: dict[str, Any], inferred_role: str | None = None) -> tuple[str, str]:
    admin_override_role = _normalize_role_value(candidate.get("admin_override_role"))
    if admin_override_role:
        return admin_override_role, "admin_override_role"

    candidate_target_role = _normalize_role_value(candidate.get("target_role"))
    if candidate_target_role:
        return candidate_target_role, "candidate_target_role"

    inferred = _normalize_role_value(inferred_role)
    if inferred:
        return inferred, "inferred_role"

    return "General Candidate", "default"


def _build_role_specific_interview_plan(interview_role: str, job_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Build a role-specific interview plan, optionally enhanced with job specification details.
    
    If job_spec is provided, generates dynamic questions tailored to the specific role requirements.
    """
    flow_by_role: dict[str, dict[str, Any]] = {
        "Frontend Developer": {
            "flow": ["UI foundations", "React architecture", "State management", "Debugging"],
            "questions": [
                "How would you structure a reusable component library for a large React app?",
                "When would you use context, reducers, or a dedicated state library?",
                "How do you improve Core Web Vitals on a slow page?",
            ],
        },
        "Backend Developer": {
            "flow": ["API design", "Data modeling", "Performance", "Reliability"],
            "questions": [
                "How do you version APIs without breaking clients?",
                "How would you model a many-to-many domain with audit history?",
                "How do you diagnose and reduce p95 latency in production?",
            ],
        },
        "Data Analyst": {
            "flow": ["Problem framing", "SQL analysis", "Dashboarding", "Insights communication"],
            "questions": [
                "How do you validate data quality before publishing analysis?",
                "Write the approach for cohort retention analysis using SQL.",
                "How would you present a conflicting metric trend to business stakeholders?",
            ],
        },
        "Machine Learning Engineer": {
            "flow": ["Feature engineering", "Model selection", "Evaluation", "MLOps"],
            "questions": [
                "How do you choose between a simpler and a more complex model?",
                "How do you detect and mitigate data leakage?",
                "What does a robust model monitoring strategy look like after deployment?",
            ],
        },
        "Product Manager": {
            "flow": ["Discovery", "Prioritization", "Execution", "Measurement"],
            "questions": [
                "How do you decide what to build when teams have conflicting priorities?",
                "Describe a framework you use for trade-offs across impact, effort, and risk.",
                "Which product metrics define success for a new onboarding flow?",
            ],
        },
        "QA Engineer": {
            "flow": ["Test strategy", "Automation", "Risk-based testing", "Release quality"],
            "questions": [
                "How do you design a test plan for a feature with tight deadlines?",
                "What should be automated first in a new test suite and why?",
                "How do you triage flaky tests without slowing delivery?",
            ],
        },
        "General Candidate": {
            "flow": ["Background", "Problem solving", "Collaboration", "Execution"],
            "questions": [
                "Walk through a challenging project and your key contributions.",
                "How do you break down ambiguous problems into actionable steps?",
                "How do you handle disagreements in cross-functional teams?",
            ],
        },
    }

    plan = flow_by_role.get(interview_role, flow_by_role["General Candidate"])
    base_plan = {
        "role": interview_role,
        "flow": plan["flow"],
        "questions": plan["questions"],
        "realtime": {
            "strategy": "dynamic_turn_based",
            "voiceProvider": "groq_browser" if settings.interview_realtime_provider == "groq" else "openai_realtime",
            "maxQuestions": max(1, settings.interview_max_questions),
            "maxDurationSeconds": max(300, settings.interview_max_duration_seconds),
            "instructions": {
                "questionPolicy": "Ask one concise question at a time and avoid repeats.",
                "grounding": "Use role context, resume summary, and job specification context when available.",
                "completionSignal": "After maxQuestions, conclude with INTERVIEW_COMPLETE.",
            },
        },
    }

    # Enhance plan with job specification if available
    if job_spec and isinstance(job_spec, dict):
        base_plan["job_context"] = {
            "title": job_spec.get("job_title"),
            "department": job_spec.get("department"),
            "seniority": job_spec.get("seniority_level"),
            "required_skills": job_spec.get("required_skills", []),
            "nice_to_have_skills": job_spec.get("nice_to_have_skills", []),
            "key_responsibilities": job_spec.get("key_responsibilities", []),
        }
        # In a future enhancement, we can generate dynamic questions using the job spec
        # For now, we include the job context for the interviewer reference
    
    return base_plan


def _effective_interview_output_mode() -> str:
    if settings.interview_realtime_provider == "groq":
        return "browser_tts"
    return settings.interview_ai_output_mode


LEETCODE_QUESTION_BANK: list[dict[str, Any]] = [
    {"id": 1, "title": "Two Sum", "difficulty": "Easy", "url": "https://leetcode.com/problems/two-sum/", "tags": ["arrays", "hashmap"], "role_focus": ["backend", "frontend", "data", "general"], "prompt": "Describe your approach, complexity, and how you would test edge cases."},
    {"id": 15, "title": "3Sum", "difficulty": "Medium", "url": "https://leetcode.com/problems/3sum/", "tags": ["arrays", "two-pointers", "sorting"], "role_focus": ["backend", "data", "general"], "prompt": "Explain how sorting + two pointers avoids duplicate triplets."},
    {"id": 20, "title": "Valid Parentheses", "difficulty": "Easy", "url": "https://leetcode.com/problems/valid-parentheses/", "tags": ["stack", "strings"], "role_focus": ["frontend", "backend", "qa", "general"], "prompt": "Walk through stack state transitions for valid and invalid inputs."},
    {"id": 53, "title": "Maximum Subarray", "difficulty": "Medium", "url": "https://leetcode.com/problems/maximum-subarray/", "tags": ["arrays", "dp"], "role_focus": ["backend", "data", "ml", "general"], "prompt": "Explain Kadane's algorithm and why it is optimal."},
    {"id": 70, "title": "Climbing Stairs", "difficulty": "Easy", "url": "https://leetcode.com/problems/climbing-stairs/", "tags": ["dp"], "role_focus": ["backend", "ml", "general"], "prompt": "Derive the recurrence and discuss space optimization."},
    {"id": 121, "title": "Best Time to Buy and Sell Stock", "difficulty": "Easy", "url": "https://leetcode.com/problems/best-time-to-buy-and-sell-stock/", "tags": ["arrays", "greedy"], "role_focus": ["backend", "data", "general"], "prompt": "Explain single-pass logic and how to justify correctness."},
    {"id": 141, "title": "Linked List Cycle", "difficulty": "Easy", "url": "https://leetcode.com/problems/linked-list-cycle/", "tags": ["linked-list", "two-pointers"], "role_focus": ["backend", "general"], "prompt": "Explain Floyd cycle detection with an example."},
    {"id": 146, "title": "LRU Cache", "difficulty": "Medium", "url": "https://leetcode.com/problems/lru-cache/", "tags": ["design", "hashmap", "linked-list"], "role_focus": ["backend", "ml", "general"], "prompt": "Describe O(1) get/put design and key implementation pitfalls."},
    {"id": 155, "title": "Min Stack", "difficulty": "Medium", "url": "https://leetcode.com/problems/min-stack/", "tags": ["stack", "design"], "role_focus": ["frontend", "backend", "qa", "general"], "prompt": "Explain how you keep min retrieval O(1)."},
    {"id": 200, "title": "Number of Islands", "difficulty": "Medium", "url": "https://leetcode.com/problems/number-of-islands/", "tags": ["graph", "dfs", "bfs"], "role_focus": ["backend", "data", "ml", "general"], "prompt": "Discuss DFS/BFS trade-offs and complexity."},
    {"id": 206, "title": "Reverse Linked List", "difficulty": "Easy", "url": "https://leetcode.com/problems/reverse-linked-list/", "tags": ["linked-list"], "role_focus": ["backend", "general"], "prompt": "Compare iterative and recursive solutions."},
    {"id": 215, "title": "Kth Largest Element in an Array", "difficulty": "Medium", "url": "https://leetcode.com/problems/kth-largest-element-in-an-array/", "tags": ["heap", "quickselect"], "role_focus": ["backend", "data", "ml", "general"], "prompt": "Explain heap vs quickselect trade-offs."},
    {"id": 238, "title": "Product of Array Except Self", "difficulty": "Medium", "url": "https://leetcode.com/problems/product-of-array-except-self/", "tags": ["arrays", "prefix-suffix"], "role_focus": ["backend", "data", "general"], "prompt": "Explain how to avoid division and keep O(1) extra space."},
    {"id": 300, "title": "Longest Increasing Subsequence", "difficulty": "Medium", "url": "https://leetcode.com/problems/longest-increasing-subsequence/", "tags": ["dp", "binary-search"], "role_focus": ["backend", "data", "ml", "general"], "prompt": "Explain O(n^2) DP and O(n log n) optimization."},
    {"id": 347, "title": "Top K Frequent Elements", "difficulty": "Medium", "url": "https://leetcode.com/problems/top-k-frequent-elements/", "tags": ["hashmap", "heap", "bucket-sort"], "role_focus": ["backend", "data", "ml", "general"], "prompt": "Describe multiple approaches and when each is preferable."},
    {"id": 417, "title": "Pacific Atlantic Water Flow", "difficulty": "Medium", "url": "https://leetcode.com/problems/pacific-atlantic-water-flow/", "tags": ["graph", "dfs", "bfs"], "role_focus": ["backend", "ml", "general"], "prompt": "Explain reverse-flow DFS/BFS intuition."},
    {"id": 560, "title": "Subarray Sum Equals K", "difficulty": "Medium", "url": "https://leetcode.com/problems/subarray-sum-equals-k/", "tags": ["arrays", "prefix-sum", "hashmap"], "role_focus": ["backend", "data", "general"], "prompt": "Explain prefix sum hashmap logic with duplicate sums."},
    {"id": 704, "title": "Binary Search", "difficulty": "Easy", "url": "https://leetcode.com/problems/binary-search/", "tags": ["binary-search"], "role_focus": ["backend", "frontend", "qa", "general"], "prompt": "Discuss loop invariants and off-by-one pitfalls."},
    {"id": 733, "title": "Flood Fill", "difficulty": "Easy", "url": "https://leetcode.com/problems/flood-fill/", "tags": ["graph", "dfs", "bfs"], "role_focus": ["frontend", "backend", "qa", "general"], "prompt": "Explain recursion vs iterative queue implementation."},
    {"id": 994, "title": "Rotting Oranges", "difficulty": "Medium", "url": "https://leetcode.com/problems/rotting-oranges/", "tags": ["graph", "bfs", "matrix"], "role_focus": ["backend", "data", "general"], "prompt": "Explain multi-source BFS and minute-level progression."},
    {"id": 1143, "title": "Longest Common Subsequence", "difficulty": "Medium", "url": "https://leetcode.com/problems/longest-common-subsequence/", "tags": ["dp", "strings"], "role_focus": ["backend", "ml", "general"], "prompt": "Build the DP table and explain transitions."},
    {"id": 125, "title": "Valid Palindrome", "difficulty": "Easy", "url": "https://leetcode.com/problems/valid-palindrome/", "tags": ["strings", "two-pointers"], "role_focus": ["frontend", "backend", "qa", "general"], "prompt": "Explain normalization and two-pointer traversal."},
    {"id": 240, "title": "Search a 2D Matrix II", "difficulty": "Medium", "url": "https://leetcode.com/problems/search-a-2d-matrix-ii/", "tags": ["matrix", "binary-search"], "role_focus": ["backend", "data", "general"], "prompt": "Explain top-right elimination strategy."},
]


def _role_focus_bucket(interview_role: str) -> str:
    normalized = (interview_role or "").strip().lower()
    if "frontend" in normalized:
        return "frontend"
    if "backend" in normalized:
        return "backend"
    if "data" in normalized or "analyst" in normalized:
        return "data"
    if "machine learning" in normalized or normalized.startswith("ml"):
        return "ml"
    if "qa" in normalized or "test" in normalized:
        return "qa"
    if "product" in normalized:
        return "pm"
    return "general"


def _extract_keywords(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_+#.-]+", (text or "").lower()))
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "have", "has", "are", "was", "were", "will", "about", "role", "candidate", "experience", "work", "using", "used", "over", "under", "than", "where", "what", "when", "how", "why", "their", "them", "then", "also", "while", "into", "onto", "across", "more", "most", "very",
    }
    return {token for token in words if len(token) > 2 and token not in stopwords}


def _derive_context_tags(keyword_set: set[str]) -> set[str]:
    tag_rules = {
        "python": {"hashmap", "arrays", "dp"},
        "javascript": {"strings", "arrays", "stack"},
        "typescript": {"strings", "arrays", "stack"},
        "react": {"strings", "stack", "arrays"},
        "node": {"hashmap", "graph"},
        "sql": {"prefix-sum", "hashmap", "arrays"},
        "postgres": {"prefix-sum", "hashmap"},
        "api": {"hashmap", "design"},
        "microservices": {"design", "graph"},
        "redis": {"design", "hashmap"},
        "cache": {"design", "linked-list", "hashmap"},
        "search": {"binary-search", "arrays"},
        "analytics": {"prefix-sum", "heap", "arrays"},
        "etl": {"arrays", "hashmap", "heap"},
        "data": {"arrays", "heap", "graph"},
        "ml": {"dp", "heap", "graph"},
        "machine": {"dp", "heap", "graph"},
        "graph": {"graph", "dfs", "bfs"},
        "tree": {"dfs", "bfs"},
        "dynamic": {"dp"},
        "testing": {"stack", "arrays", "strings"},
        "quality": {"stack", "arrays", "strings"},
    }

    tags: set[str] = set()
    for keyword in keyword_set:
        tags.update(tag_rules.get(keyword, set()))
    return tags


def _already_asked_leetcode_ids(transcript_turns: list[dict[str, Any]]) -> set[int]:
    transcript_blob = "\n".join(
        str(turn.get("text") or "") for turn in transcript_turns if isinstance(turn, dict)
    ).lower()
    asked: set[int] = set()
    for question in LEETCODE_QUESTION_BANK:
        qid = question.get("id")
        title = str(question.get("title") or "").lower()
        prompt = str(question.get("prompt") or "").lower()
        prompt_signature = prompt.split(".")[0].strip()
        if not isinstance(qid, int):
            continue
        if (
            f"leetcode {qid}" in transcript_blob
            or (title and title in transcript_blob)
            or (prompt_signature and prompt_signature in transcript_blob)
        ):
            asked.add(qid)
    return asked


def _infer_questions_asked_from_transcript(transcript_turns: list[dict[str, Any]]) -> int:
    max_prefixed_ordinal = 0
    ai_turn_count = 0

    for turn in transcript_turns:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker") or "").strip().lower()
        if speaker != "ai":
            continue

        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        ai_turn_count += 1

        matched = re.match(r"^Q\s*(\d+)\s*/\s*\d+", text, flags=re.IGNORECASE)
        if matched:
            try:
                max_prefixed_ordinal = max(max_prefixed_ordinal, int(matched.group(1)))
            except ValueError:
                pass

    return max(max_prefixed_ordinal, ai_turn_count)


def _already_asked_role_theory_indexes(transcript_turns: list[dict[str, Any]], role_questions: list[str]) -> set[int]:
    transcript_blob = "\n".join(
        str(turn.get("text") or "") for turn in transcript_turns if isinstance(turn, dict)
    ).lower()
    asked_indexes: set[int] = set()
    for index, question in enumerate(role_questions):
        signature = normalize = " ".join(question.lower().split())
        if not signature:
            continue
        # Match by first clause to tolerate punctuation differences from client rendering.
        first_clause = signature.split("?")[0].strip()
        if first_clause and first_clause in transcript_blob:
            asked_indexes.add(index)
    return asked_indexes


def _build_role_theory_questions(
    interview_role: str,
    interview_plan: dict[str, Any],
    resume_summary: str,
) -> list[str]:
    job_context = interview_plan.get("job_context") if isinstance(interview_plan.get("job_context"), dict) else {}
    flow_topics = interview_plan.get("flow") if isinstance(interview_plan.get("flow"), list) else []

    job_title = str(job_context.get("title") or interview_role or "this role").strip()
    required_skills = [str(skill).strip() for skill in (job_context.get("required_skills") or []) if str(skill).strip()]
    responsibilities = [str(item).strip() for item in (job_context.get("key_responsibilities") or []) if str(item).strip()]
    flow_topic_1 = str(flow_topics[0]).strip() if flow_topics else "problem solving"
    flow_topic_2 = str(flow_topics[1]).strip() if len(flow_topics) > 1 else "execution"
    skill_focus = required_skills[0] if required_skills else "core technical fundamentals"
    skill_secondary = required_skills[1] if len(required_skills) > 1 else "system design"
    responsibility_focus = responsibilities[0] if responsibilities else "delivering production-ready features"
    resume_focus = (resume_summary or "").strip()
    if len(resume_focus) > 180:
        resume_focus = resume_focus[:177].rstrip() + "..."
    resume_focus = resume_focus or "your recent project experience"

    return [
        f"For a {job_title} role, how would you plan and prioritize work around {responsibility_focus}, and what trade-offs would you make?",
        f"Based on your resume mention of {resume_focus}, how would that experience help you handle {flow_topic_1} and {flow_topic_2} in this role?",
        f"This job emphasizes {skill_focus} and {skill_secondary}; what practical approach would you follow to deliver impact in your first 90 days?",
    ]


def _generate_next_interview_question_from_leetcode(
    interview_role: str,
    interview_plan: dict[str, Any],
    resume_summary: str,
    transcript_turns: list[dict[str, Any]],
    next_question_number: int,
    max_questions: int,
) -> str:
    role_bucket = _role_focus_bucket(interview_role)
    job_context = interview_plan.get("job_context") if isinstance(interview_plan.get("job_context"), dict) else {}

    required_skills = job_context.get("required_skills") if isinstance(job_context.get("required_skills"), list) else []
    nice_to_have_skills = job_context.get("nice_to_have_skills") if isinstance(job_context.get("nice_to_have_skills"), list) else []
    key_responsibilities = job_context.get("key_responsibilities") if isinstance(job_context.get("key_responsibilities"), list) else []
    job_title = str(job_context.get("title") or "")

    context_blob = " ".join(
        [
            interview_role,
            resume_summary,
            job_title,
            " ".join(str(skill) for skill in required_skills),
            " ".join(str(skill) for skill in nice_to_have_skills),
            " ".join(str(resp) for resp in key_responsibilities),
        ]
    )
    context_keywords = _extract_keywords(context_blob)
    context_tags = _derive_context_tags(context_keywords)

    coding_target = 3 if max_questions >= 6 else max(1, max_questions // 2)
    role_target = 3 if max_questions >= 6 else max(0, max_questions - coding_target)

    # Phase 1: coding theory questions (first 3 out of 6).
    if next_question_number <= coding_target:
        asked_ids = _already_asked_leetcode_ids(transcript_turns)
        available_questions = [
            question for question in LEETCODE_QUESTION_BANK
            if isinstance(question.get("id"), int) and question.get("id") not in asked_ids
        ]
        if not available_questions:
            available_questions = LEETCODE_QUESTION_BANK

        scored_questions: list[tuple[float, dict[str, Any]]] = []
        for index, question in enumerate(available_questions):
            score = 0.0
            question_tags = set(question.get("tags") or [])
            question_role_focus = set(question.get("role_focus") or [])

            if role_bucket in question_role_focus:
                score += 4.0
            if "general" in question_role_focus:
                score += 1.0

            score += float(len(question_tags & context_tags)) * 2.0

            question_text_blob = f"{question.get('title') or ''} {question.get('prompt') or ''}".lower()
            keyword_overlap = len(_extract_keywords(question_text_blob) & context_keywords)
            score += float(min(keyword_overlap, 4))

            score -= index * 0.01
            scored_questions.append((score, question))

        scored_questions.sort(key=lambda item: item[0], reverse=True)
        coding_position = max(0, next_question_number - 1)
        if coding_position < len(scored_questions):
            selected = scored_questions[coding_position][1]
        else:
            selected = scored_questions[0][1]
        base_question = str(selected.get("prompt") or "Explain your approach, complexity, and edge cases.")
    else:
        # Phase 2: role/job-title theory questions (next 3 out of 6).
        role_questions = _build_role_theory_questions(
            interview_role=interview_role,
            interview_plan=interview_plan,
            resume_summary=resume_summary,
        )
        asked_indexes = _already_asked_role_theory_indexes(transcript_turns, role_questions)
        remaining_questions = [
            question for index, question in enumerate(role_questions) if index not in asked_indexes
        ]
        if not remaining_questions:
            remaining_questions = role_questions

        # Preserve deterministic ordering for a stable 3-question theory block.
        role_position = next_question_number - coding_target - 1
        if role_target > 0:
            role_position = min(role_position, role_target - 1)
        role_position = max(0, role_position)

        if role_position < len(remaining_questions):
            base_question = remaining_questions[role_position]
        else:
            base_question = remaining_questions[0]

    expected_prefix = f"Q{next_question_number}/{max_questions}:"
    return f"{expected_prefix} {base_question}"


def _supabase_request(
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    bearer_token: str | None = None,
    use_service_role: bool = False,
) -> Any:
    if not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL is not configured",
        )

    api_key = settings.supabase_service_role_key if use_service_role else settings.supabase_anon_key
    auth_token = settings.supabase_service_role_key if use_service_role else bearer_token

    if not api_key or not auth_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase credentials are not configured",
        )

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    data = None if body is None else json.dumps(body).encode("utf-8")
    url = f"{settings.supabase_url.rstrip('/')}{path}"
    req = request.Request(url, data=data, headers=headers, method=method)

    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8") if exc.fp else ""
        raise SupabaseError(raw_error or exc.reason) from exc
    except error.URLError as exc:
        raise SupabaseError(f"supabase_network_error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise SupabaseError("supabase_network_error: request timed out") from exc


def _get_bearer_token(request_obj: Request) -> str:
    authorization = request_obj.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Supabase access token",
        )

    return authorization.split(" ", 1)[1].strip()


def _get_supabase_user(access_token: str) -> dict[str, Any]:
    try:
        user = _supabase_request(
            "/auth/v1/user",
            method="GET",
            bearer_token=access_token,
        )
    except SupabaseError as exc:
        if _is_supabase_network_error(str(exc)):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable. Please try again shortly.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Supabase access token",
        ) from exc

    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Supabase user payload",
        )

    return user


def _candidate_name_from_user(user: dict[str, Any]) -> str:
    email = user.get("email") or ""
    if email:
        return email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
    return "Candidate"


def _is_admin(user: dict[str, Any]) -> bool:
    app_metadata_role = (user.get("app_metadata") or {}).get("role")
    if app_metadata_role == "admin":
        return True

    metadata_role = (user.get("user_metadata") or {}).get("role")
    if metadata_role == "admin":
        return True

    email = str(user.get("email") or "").strip().lower()
    return "admin" in email


def _get_or_create_candidate(user: dict[str, Any]) -> dict[str, Any]:
    user_id = user["id"]
    candidate_name = _candidate_name_from_user(user)

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?user_id=eq.{quote(user_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if candidate_rows:
        return candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows

    _supabase_request(
        "/rest/v1/candidates?select=*",
        method="POST",
        body={
            "user_id": user_id,
            "full_name": candidate_name,
            "role": "candidate",
            "current_stage": "profile_pending",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    # PostgREST may return an empty body for inserts unless return=representation is requested.
    # Always re-fetch to reliably return the candidate row.
    refreshed_rows = _supabase_request(
        f"/rest/v1/candidates?user_id=eq.{quote(user_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not refreshed_rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create candidate profile",
        )

    return refreshed_rows[0] if isinstance(refreshed_rows, list) else refreshed_rows


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except Exception:
        return False


def _assert_safe_storage_path(path: str) -> None:
    # Disallow traversal, null-byte, Windows separators, and malformed segments.
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Storage path is required",
        )

    normalized = path.strip()
    if normalized.startswith("/") or ".." in normalized or "\x00" in normalized or "\\" in normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )

    if "//" in normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )

    if not re.fullmatch(r"[A-Za-z0-9._/-]+", normalized):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )

    parts = normalized.split("/")
    if any(part == "" for part in parts):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid storage path",
        )


def _normalize_hiring_outcome(value: str | None) -> str | None:
    normalized = _normalize_role_value(value)
    if not normalized:
        return None
    lowered = normalized.lower()
    if lowered not in {"hired", "not_hired"}:
        return None
    return lowered


def _delete_storage_object(path: str, bucket_id: str) -> None:
    _assert_safe_storage_path(path)
    encoded_path = quote(path, safe="/")
    try:
        _supabase_request(
            f"/storage/v1/object/{bucket_id}/{encoded_path}",
            method="DELETE",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    except SupabaseError as exc:
        # Treat already-missing objects as non-fatal for idempotent cleanup.
        if "not found" in str(exc).lower() or "404" in str(exc):
            return
        raise


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _revoke_interview_upload_nonces(candidate_id: str, session_id: str, file_type: str) -> None:
    nonce_rows = _supabase_request(
        f"/rest/v1/interview_upload_nonces?candidate_id=eq.{quote(candidate_id)}&session_id=eq.{quote(session_id)}&file_type=eq.{quote(file_type)}&used=eq.false&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    for nonce_row in nonce_rows if isinstance(nonce_rows, list) else []:
        nonce_id = nonce_row.get("id")
        if not nonce_id:
            continue
        _supabase_request(
            f"/rest/v1/interview_upload_nonces?id=eq.{quote(str(nonce_id))}",
            method="DELETE",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )


def _get_interview_upload_nonce(nonce_id: str, candidate_id: str, session_id: str, file_type: str) -> dict[str, Any] | None:
    nonce_rows = _supabase_request(
        f"/rest/v1/interview_upload_nonces?id=eq.{quote(nonce_id)}&candidate_id=eq.{quote(candidate_id)}&session_id=eq.{quote(session_id)}&file_type=eq.{quote(file_type)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not nonce_rows:
        return None
    return nonce_rows[0] if isinstance(nonce_rows, list) else nonce_rows


def _mark_interview_upload_nonce_used(nonce_id: str) -> None:
    _supabase_request(
        f"/rest/v1/interview_upload_nonces?id=eq.{quote(nonce_id)}",
        method="PATCH",
        body={
            "used": True,
            "used_at": datetime.now(UTC).isoformat(),
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )


def _delete_interview_upload_nonces_for_session(session_id: str, candidate_id: str | None = None) -> None:
    query = f"/rest/v1/interview_upload_nonces?session_id=eq.{quote(session_id)}&select=*"
    if candidate_id:
        query = f"/rest/v1/interview_upload_nonces?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate_id)}&select=*"

    nonce_rows = _supabase_request(
        query,
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    for nonce_row in nonce_rows if isinstance(nonce_rows, list) else []:
        nonce_id = nonce_row.get("id")
        if not nonce_id:
            continue
        _supabase_request(
            f"/rest/v1/interview_upload_nonces?id=eq.{quote(str(nonce_id))}",
            method="DELETE",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )


def _build_storage_signed_upload_url(path: str, bucket_id: str = "resumes", is_public: bool = True) -> dict[str, str]:
    _assert_safe_storage_path(path)
    encoded_path = quote(path, safe="/")
    try:
        payload = _supabase_request(
            f"/storage/v1/object/upload/sign/{bucket_id}/{encoded_path}",
            method="POST",
            body={},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    except SupabaseError as exc:
        # Supabase returns a 404-style payload when the storage bucket is missing.
        if "related resource does not exist" not in str(exc).lower():
            raise

        _supabase_request(
            "/storage/v1/bucket",
            method="POST",
            body={
                "id": bucket_id,
                "name": bucket_id,
                "public": is_public,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

        payload = _supabase_request(
            f"/storage/v1/object/upload/sign/{bucket_id}/{encoded_path}",
            method="POST",
            body={},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected storage signing response",
        )

    url_path = payload.get("url")
    if not isinstance(url_path, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Storage signing URL missing in response",
        )

    signed_url = f"{settings.supabase_url.rstrip('/')}/storage/v1{url_path}"
    return {
        "signedUrl": signed_url,
        "path": path,
        "bucket": bucket_id,
    }


def _build_storage_signed_read_url(path: str, bucket_id: str) -> dict[str, str]:
    encoded_path = quote(path, safe="/")
    payload = _supabase_request(
        f"/storage/v1/object/sign/{bucket_id}/{encoded_path}",
        method="POST",
        body={
            "expiresIn": 3600,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected storage signing response",
        )

    signed_url = payload.get("signedURL") or payload.get("signedUrl") or payload.get("url")
    if not isinstance(signed_url, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Storage signed read URL missing in response",
        )

    if signed_url.startswith("/"):
        signed_url = f"{settings.supabase_url.rstrip('/')}/storage/v1{signed_url}"

    return {
        "signedUrl": signed_url,
        "path": path,
        "bucket": bucket_id,
    }


def _create_openai_realtime_session(
    interview_role: str,
    interview_plan: dict[str, Any],
    resume_summary: str,
    include_client_secret: bool = False,
) -> dict[str, Any] | None:
    provider = get_llm_provider_by_name(settings.interview_realtime_provider)
    if not provider.is_configured():
        return None
    try:
        return provider.create_realtime_session(
            interview_role=interview_role,
            interview_plan=interview_plan,
            resume_summary=resume_summary,
            include_client_secret=include_client_secret,
        )
    except Exception:
        return None


def _get_current_application_stage(candidate: dict[str, Any]) -> str:
    stage = _normalize_role_value(candidate.get("current_stage"))
    return stage or "profile_pending"


def _download_url_bytes(file_url: str) -> bytes:
    with request.urlopen(file_url, timeout=30) as response:
        return response.read()


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:  # pragma: no cover - handled by fallback summary
        raise SupabaseError(f"Unable to parse PDF: {exc}") from exc

    text_parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            text_parts.append(page_text)

    return "\n".join(text_parts).strip()


def _build_resume_prompt(
    candidate: dict[str, Any],
    latest_upload: dict[str, Any],
    extracted_text: str,
    interview_role: str,
) -> str:
    candidate_name = candidate.get("full_name", "the candidate")
    file_name = latest_upload.get("file_name", "resume.pdf")
    excerpt = extracted_text[:12000] if extracted_text else "No text could be extracted from the PDF."

    return (
        "You are an expert recruitment analyst. Review the resume content and return only valid JSON. "
        "Do not include markdown. The JSON object must contain keys: summary (string), skills (array of strings), "
        "experience_level (string), transcript (string), resume_components (object), resume_score (integer 0-100). "
        "The resume_components object must contain integer scores from 0 to 10 for: skills_match, experience, projects, education, quality. "
        "Use the provided job role as the evaluation target and judge only what is supported by the resume. "
        f"Candidate name: {candidate_name}. Target interview role: {interview_role}. File name: {file_name}. "
        f"Resume text:\n{excerpt}"
    )


def _extract_openai_error(raw_error: str) -> tuple[str | None, str | None]:
    if not raw_error:
        return None, None

    try:
        parsed = json.loads(raw_error)
    except Exception:
        normalized = raw_error.lower()
        if "insufficient_quota" in normalized:
            return "insufficient_quota", None
        return None, raw_error

    if not isinstance(parsed, dict):
        return None, raw_error

    error_obj = parsed.get("error")
    if isinstance(error_obj, dict):
        code = error_obj.get("code") if isinstance(error_obj.get("code"), str) else None
        message = error_obj.get("message") if isinstance(error_obj.get("message"), str) else None
        return code, message

    return None, raw_error


def _friendly_scoring_error_message(raw_message: str | None) -> str:
    normalized = (raw_message or "").lower()

    if "insufficient_quota" in normalized or "quota" in normalized or "billing" in normalized:
        return "Scoring provider quota exceeded. Please retry later or contact support."
    if "provider is not configured" in normalized or "missing_key" in normalized:
        return "Scoring provider is not configured. Please contact support."
    if "invalid api key" in normalized or "authentication" in normalized:
        return "Scoring provider authentication failed. Please contact support."

    return "Scoring provider unavailable. Please try again shortly."


def _friendly_interview_provider_error_message(raw_message: str | None) -> str:
    normalized = (raw_message or "").lower()

    if "insufficient_quota" in normalized or "quota" in normalized or "billing" in normalized:
        return "Interview question provider quota exceeded. Please retry later."
    if "provider is not configured" in normalized or "missing_key" in normalized or "not configured" in normalized:
        return "Interview question provider is not configured. Please contact support."
    if (
        "invalid api key" in normalized
        or "incorrect api key" in normalized
        or "invalid_api_key" in normalized
        or "authentication" in normalized
        or "unauthorized" in normalized
    ):
        return "Interview question provider authentication failed. Please contact support."

    return "Interview question provider unavailable. Please try again shortly."


def _openai_chat_completion_with_retry(payload: dict[str, Any], timeout_seconds: int = 60) -> dict[str, Any]:
    provider_chain = get_llm_provider_chain(settings.llm_provider, settings.llm_provider_fallbacks)
    configured_chain = [provider for provider in provider_chain if provider.is_configured()]
    if not configured_chain:
        raise SupabaseError("No configured LLM provider found. Check LLM_PROVIDER and fallback keys.")

    max_attempts = 3
    backoff_seconds = [0.8, 1.6, 3.2]
    last_error: Exception | None = None

    for provider in configured_chain:
        for attempt in range(max_attempts):
            try:
                return provider.chat_completion(payload, timeout_seconds=timeout_seconds)
            except LLMProviderError as exc:
                last_error = exc
                # Quota/auth/config failures should trigger provider fallback quickly.
                if exc.code in {"insufficient_quota", "invalid_api_key", "missing_key"}:
                    break
                if attempt < max_attempts - 1 and exc.retryable:
                    time.sleep(backoff_seconds[attempt])
                    continue
                break
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    time.sleep(backoff_seconds[attempt])
                    continue
                break

    if isinstance(last_error, LLMProviderError) and last_error.code == "insufficient_quota":
        raise SupabaseError("Scoring provider quota exceeded. Please retry later.") from last_error
    raise SupabaseError(_friendly_scoring_error_message(str(last_error) if last_error else "LLM providers unavailable"))


def _ensure_openai_scoring_ready() -> None:
    provider_chain = get_llm_provider_chain(settings.llm_provider, settings.llm_provider_fallbacks)
    if not any(provider.is_configured() for provider in provider_chain):
        raise SupabaseError("No configured LLM provider found. Check LLM_PROVIDER and fallback keys.")

    # Avoid blocking interview start on external LLM health checks.
    # Actual scoring calls still run later and already have retry/error handling.


def _to_scoring_provider_http_exception(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_friendly_scoring_error_message(str(exc)),
    )


def _openai_resume_analysis(
    candidate: dict[str, Any],
    latest_upload: dict[str, Any],
    extracted_text: str,
    interview_role: str,
) -> dict[str, Any]:
    prompt = _build_resume_prompt(candidate, latest_upload, extracted_text, interview_role)
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": "You analyze resumes and respond with strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    data = _openai_chat_completion_with_retry(payload, timeout_seconds=60)

    content = (((data.get("choices") or [])[0] or {}).get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise SupabaseError("LLM provider returned an empty analysis payload")

    parsed = json.loads(content)
    summary = str(parsed.get("summary") or "").strip()
    skills = parsed.get("skills") or []
    if not isinstance(skills, list):
        skills = []
    cleaned_skills = [str(skill).strip() for skill in skills if str(skill).strip()]
    experience_level = str(parsed.get("experience_level") or "Mid level").strip() or "Mid level"
    resume_components_raw = parsed.get("resume_components") if isinstance(parsed.get("resume_components"), dict) else {}
    resume_components = {
        "skillsMatch": resume_components_raw.get("skills_match", parsed.get("skills_match")),
        "experience": resume_components_raw.get("experience", parsed.get("experience")),
        "projects": resume_components_raw.get("projects", parsed.get("projects")),
        "education": resume_components_raw.get("education", parsed.get("education")),
        "quality": resume_components_raw.get("quality", parsed.get("quality")),
    }
    score = _calculate_resume_score(resume_components)
    transcript = str(parsed.get("transcript") or summary or "Resume analysis completed.").strip()

    if not summary:
        summary = transcript

    return {
        "ai_summary": summary,
        "ai_score": score,
        "ai_skills": cleaned_skills,
        "ai_experience_level": experience_level,
        "ai_generated_at": datetime.now(UTC).isoformat(),
        "ai_transcript": transcript,
        "ai_score_payload": {
            "resumeComponents": resume_components,
            "resumeScore": score,
            "scoringVersion": "phase3-resume-v1",
            "llmResumeScore": parsed.get("resume_score"),
        },
    }


def _build_resume_analysis(candidate: dict[str, Any], latest_upload: dict[str, Any]) -> dict[str, Any]:
    file_url = latest_upload.get("file_url")
    file_name = latest_upload.get("file_name") or "resume.pdf"

    extracted_text = ""
    if isinstance(file_url, str) and file_url:
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(file_url))
        except Exception:
            extracted_text = ""

    inferred_role = _infer_interview_role_from_resume_text(extracted_text)
    resolved_interview_role, resolved_role_source = _resolve_interview_role(candidate, inferred_role)
    normalized_role = resolved_interview_role.lower()

    analysis = _openai_resume_analysis(candidate, latest_upload, extracted_text, resolved_interview_role)
    analysis["ai_transcript"] = (
        f"Interview role source: {resolved_role_source}. "
        f"Target role used for analysis: {resolved_interview_role}. "
        f"{analysis.get('ai_transcript', '')}"
    ).strip()
    return analysis


def _persist_candidate_analysis(candidate_id: str, analysis: dict[str, Any]) -> None:
    payload = dict(analysis or {})

    try:
        _supabase_request(
            f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
            method="PATCH",
            body=payload,
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        return
    except SupabaseError as exc:
        # Backward-compatible fallback for deployments where newer optional columns
        # (for example ai_experience_level) are not yet present in schema cache.
        err_text = str(exc)
        if "Could not find the '" not in err_text or "column of 'candidates'" not in err_text:
            raise

        missing_col_match = re.search(r"Could not find the '([^']+)' column", err_text)
        if not missing_col_match:
            raise

        missing_col = missing_col_match.group(1)
        if missing_col not in payload:
            raise

        payload.pop(missing_col, None)
        if not payload:
            return

        _supabase_request(
            f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
            method="PATCH",
            body=payload,
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )


def _parse_job_specification(raw_text: str) -> dict[str, Any]:
    """
    Parse raw job specification text into structured JSON using OpenAI.
    Returns a dict with required_skills, nice_to_have_skills, seniority, responsibilities, evaluation_rubric.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Job specification text is empty")
    
    prompt = f"""Analyze the following job specification and extract structured information.
Return ONLY valid JSON (no markdown, no extra text) with these exact fields:

{{
  "job_title": "string",
  "required_skills": ["string"],
  "nice_to_have_skills": ["string"],
  "seniority_level": "Junior|Mid-level|Senior|Lead",
  "department": "string",
  "key_responsibilities": ["string"],
  "evaluation_rubric": {{
    "technical_fit": "description",
    "experience_fit": "description",
    "communication_fit": "description",
    "domain_knowledge": "description"
  }},
  "min_years_experience": integer,
  "max_years_experience": integer,
  "salary_range": "string or null",
  "summary": "string"
}}

Job Specification:
{raw_text}"""

    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": "You are a job specification analyzer. Extract structured data and respond with strict JSON only—no markdown, no additional text."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }

    try:
        data = _openai_chat_completion_with_retry(payload, timeout_seconds=45)
        content = (((data.get("choices") or [])[0] or {}).get("message") or {}).get("content")
        
        if not isinstance(content, str) or not content.strip():
            raise SupabaseError("LLM provider returned empty job spec analysis")
        
        parsed = json.loads(content)
        return {
            "job_title": str(parsed.get("job_title", "Unknown Position")).strip(),
            "required_skills": parsed.get("required_skills", []) if isinstance(parsed.get("required_skills"), list) else [],
            "nice_to_have_skills": parsed.get("nice_to_have_skills", []) if isinstance(parsed.get("nice_to_have_skills"), list) else [],
            "seniority_level": str(parsed.get("seniority_level", "Mid-level")).strip(),
            "department": str(parsed.get("department", "")).strip(),
            "key_responsibilities": parsed.get("key_responsibilities", []) if isinstance(parsed.get("key_responsibilities"), list) else [],
            "evaluation_rubric": parsed.get("evaluation_rubric", {}) if isinstance(parsed.get("evaluation_rubric"), dict) else {},
            "min_years_experience": parsed.get("min_years_experience"),
            "max_years_experience": parsed.get("max_years_experience"),
            "salary_range": parsed.get("salary_range"),
            "summary": str(parsed.get("summary", "")).strip(),
        }
    except json.JSONDecodeError as e:
        raise SupabaseError(f"Failed to parse job specification: {str(e)}")


def _clamp_component_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except Exception:
        score = 0
    return max(0, min(score, 10))


def _calculate_resume_score(components: dict[str, Any]) -> int:
    skills = _clamp_component_score(components.get("skillsMatch"))
    experience = _clamp_component_score(components.get("experience"))
    projects = _clamp_component_score(components.get("projects"))
    education = _clamp_component_score(components.get("education"))
    quality = _clamp_component_score(components.get("quality"))

    weighted_value = (
        skills * 1.0
        + experience * 0.8
        + projects * 0.6
        + education * 0.3
        + quality * 0.3
    ) * 3.0
    return max(0, min(int(round(weighted_value)), 100))


def _calculate_interview_score(components: dict[str, Any]) -> int:
    technical = _clamp_component_score(components.get("technicalAccuracy"))
    problem_solving = _clamp_component_score(components.get("problemSolving"))
    communication = _clamp_component_score(components.get("communication"))
    confidence = _clamp_component_score(components.get("confidence"))
    relevance = _clamp_component_score(components.get("relevance"))

    weighted_value = (
        technical * 2.0
        + problem_solving * 1.5
        + communication * 1.0
        + confidence * 1.0
        + relevance * 0.5
    ) * 3.0
    return max(0, min(int(round(weighted_value)), 100))


def _build_interview_prompt(
    interview_role: str,
    interview_plan: dict[str, Any],
    question_answer_pairs: list[dict[str, str]],
    transcript_turns: list[dict[str, Any]] | None,
    duration_seconds: int | None,
) -> str:
    question_payload = json.dumps(question_answer_pairs, ensure_ascii=True)
    turn_payload = json.dumps(transcript_turns or [], ensure_ascii=True)
    plan_payload = json.dumps(interview_plan, ensure_ascii=True)
    return (
        "You are an interview evaluator. Review the supplied job role, interview plan, and Q&A pairs. "
        "Return only valid JSON. Do not include markdown. The JSON object must contain keys: "
        "question_evaluations (array), behavior_score (integer 0-10), behavior_notes (string), summary (string), "
        "strengths (array of strings), concerns (array of strings). "
        "Each question_evaluations item must contain question_index (integer), technical_accuracy (integer 0-10), "
        "problem_solving (integer 0-10), communication (integer 0-10), confidence (integer 0-10), relevance (integer 0-10), notes (string). "
        "Judge each answer independently against the job role and question asked. "
        "For behavior_score, consider filler words, pauses, and hesitation using the transcript turns and timestamps when available. "
        f"Role: {interview_role}. DurationSeconds: {duration_seconds if duration_seconds is not None else 'unknown'}. "
        f"Interview plan: {plan_payload}. Q&A pairs: {question_payload}. Transcript turns: {turn_payload}."
    )


def _openai_interview_analysis(
    interview_role: str,
    interview_plan: dict[str, Any],
    question_answer_pairs: list[dict[str, str]],
    transcript_turns: list[dict[str, Any]] | None,
    duration_seconds: int | None,
) -> dict[str, Any]:
    prompt = _build_interview_prompt(interview_role, interview_plan, question_answer_pairs, transcript_turns, duration_seconds)
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": "You evaluate interview responses and respond with strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    data = _openai_chat_completion_with_retry(payload, timeout_seconds=90)

    content = (((data.get("choices") or [])[0] or {}).get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise SupabaseError("LLM provider returned an empty interview analysis payload")

    parsed = json.loads(content)
    question_evaluations = parsed.get("question_evaluations") or []
    if not isinstance(question_evaluations, list):
        question_evaluations = []

    normalized_evaluations: list[dict[str, Any]] = []
    for evaluation in question_evaluations:
        if not isinstance(evaluation, dict):
            continue
        normalized_evaluations.append(
            {
                "questionIndex": int(evaluation.get("question_index") or 0),
                "technicalAccuracy": _clamp_component_score(evaluation.get("technical_accuracy")),
                "problemSolving": _clamp_component_score(evaluation.get("problem_solving")),
                "communication": _clamp_component_score(evaluation.get("communication")),
                "confidence": _clamp_component_score(evaluation.get("confidence")),
                "relevance": _clamp_component_score(evaluation.get("relevance")),
                "notes": str(evaluation.get("notes") or "").strip(),
            }
        )

    if not normalized_evaluations:
        raise SupabaseError("Interview analysis returned no question evaluations")

    behavior_score = _clamp_component_score(parsed.get("behavior_score"))
    behavior_notes = str(parsed.get("behavior_notes") or "").strip()
    summary = str(parsed.get("summary") or "").strip()
    strengths = parsed.get("strengths") or []
    concerns = parsed.get("concerns") or []
    if not isinstance(strengths, list):
        strengths = []
    if not isinstance(concerns, list):
        concerns = []

    return {
        "questionEvaluations": normalized_evaluations,
        "behaviorScore": behavior_score,
        "behaviorNotes": behavior_notes,
        "summary": summary,
        "strengths": [str(item).strip() for item in strengths if str(item).strip()],
        "concerns": [str(item).strip() for item in concerns if str(item).strip()],
        "scoringVersion": "phase3-interview-v1",
    }


def _average_interview_dimension(question_evaluations: list[dict[str, Any]], key: str) -> float:
    values = [
        _clamp_component_score(evaluation.get(key))
        for evaluation in question_evaluations
        if isinstance(evaluation, dict)
    ]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _build_interview_scoring_rubric(
    transcript: str | None,
    transcript_turns: list[dict[str, Any]] | None,
    duration_seconds: int | None,
    total_questions: int,
    resume_score: int,
    interview_role: str,
    interview_plan: dict[str, Any],
) -> dict[str, Any]:
    turns = transcript_turns if isinstance(transcript_turns, list) else []

    candidate_turns = [
        turn
        for turn in turns
        if isinstance(turn, dict)
        and str(turn.get("speaker") or "").strip().lower() == "candidate"
        and str(turn.get("text") or "").strip()
    ]
    ai_turns = [
        turn
        for turn in turns
        if isinstance(turn, dict)
        and str(turn.get("speaker") or "").strip().lower() == "ai"
        and str(turn.get("text") or "").strip()
    ]

    question_answer_pairs: list[dict[str, str]] = []
    for index, candidate_turn in enumerate(candidate_turns):
        question_text = ""
        if index < len(ai_turns):
            question_text = str(ai_turns[index].get("text") or "").strip()
        answer_text = str(candidate_turn.get("text") or "").strip()
        if answer_text:
            question_answer_pairs.append({"question": question_text, "answer": answer_text})

    if not question_answer_pairs and transcript:
        question_answer_pairs.append({"question": "", "answer": transcript.strip()})

    analysis = _openai_interview_analysis(
        interview_role=interview_role,
        interview_plan=interview_plan,
        question_answer_pairs=question_answer_pairs,
        transcript_turns=turns,
        duration_seconds=duration_seconds,
    )

    question_evaluations = analysis.get("questionEvaluations") if isinstance(analysis.get("questionEvaluations"), list) else []
    interview_components = {
        "technicalAccuracy": _average_interview_dimension(question_evaluations, "technicalAccuracy"),
        "problemSolving": _average_interview_dimension(question_evaluations, "problemSolving"),
        "communication": _average_interview_dimension(question_evaluations, "communication"),
        "confidence": _average_interview_dimension(question_evaluations, "confidence"),
        "relevance": _average_interview_dimension(question_evaluations, "relevance"),
    }

    interview_score = _calculate_interview_score(interview_components)
    behavior_score = _clamp_component_score(analysis.get("behaviorScore"))

    resume_score = max(0, min(int(resume_score), 100))

    overall_score = int(round((resume_score * 0.3) + (interview_score * 0.6) + behavior_score))
    overall_score = max(0, min(overall_score, 100))

    return {
        "overallScore": overall_score,
        "resumeScore": resume_score,
        "interviewScore": interview_score,
        "behaviorScore": behavior_score,
        "answeredCount": len(question_answer_pairs),
        "totalQuestions": max(total_questions, len(question_answer_pairs), 1),
        "components": {
            "resume": resume_score,
            "interview": interview_score,
            "behavior": behavior_score,
        },
        "behaviorDetails": {
            "behaviorScore": behavior_score,
            "behaviorNotes": analysis.get("behaviorNotes", ""),
        },
        "interviewComponentAverages": interview_components,
        "questionEvaluations": question_evaluations,
        "llmAnalysis": analysis,
        "version": "phase3-scoring-v1",
    }


def _candidate_detail_payload(
    candidate: dict[str, Any],
    latest_upload: dict[str, Any] | None,
    slots: list[dict[str, Any]],
    interview_sessions: list[dict[str, Any]] | None = None,
    inferred_role: str | None = None,
) -> dict[str, Any]:
    analysis_summary = candidate.get("ai_summary")
    analysis_score = candidate.get("ai_score")
    analysis_skills = candidate.get("ai_skills") or []
    analysis_level = candidate.get("ai_experience_level") or "Mid level"
    analysis_transcript = candidate.get("ai_transcript") or analysis_summary
    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)

    return {
        "candidate": {
            "id": candidate["id"],
            "name": candidate.get("full_name", "Candidate"),
            "position": interview_role,
            "authRole": candidate.get("role", "candidate"),
            "targetRole": candidate.get("target_role"),
            "adminOverrideRole": candidate.get("admin_override_role"),
            "interviewRole": interview_role,
            "interviewRoleSource": role_source,
            "stage": candidate.get("current_stage", "profile_pending"),
            "score": analysis_score if isinstance(analysis_score, int) else 70 + min((len(slots) if isinstance(slots, list) else 0) * 5, 25),
            "aiSummary": analysis_summary,
            "aiSkills": analysis_skills,
            "aiExperienceLevel": analysis_level,
        },
        "latestUpload": latest_upload,
        "slots": slots if isinstance(slots, list) else [],
        "interviewSessions": interview_sessions if isinstance(interview_sessions, list) else [],
        "transcript": analysis_transcript or "Upload a resume to generate an AI summary.",
        "summary": analysis_summary or "AI resume analysis will appear here after the first run.",
    }


def _admin_refetch_candidate_detail(candidate_id: str) -> dict[str, Any]:
    refreshed_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    refreshed_candidate = refreshed_rows[0] if isinstance(refreshed_rows, list) else refreshed_rows

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate_id)}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None
    return _candidate_detail_payload(refreshed_candidate, latest_upload, slots if isinstance(slots, list) else [], [])


def _store_background_job(job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with BACKGROUND_JOB_LOCK:
        BACKGROUND_JOBS[job_id] = {**BACKGROUND_JOBS.get(job_id, {}), **updates}
        return dict(BACKGROUND_JOBS[job_id])


def _get_background_job(job_id: str) -> dict[str, Any] | None:
    with BACKGROUND_JOB_LOCK:
        job = BACKGROUND_JOBS.get(job_id)
        return dict(job) if job else None


def _submit_background_job(job_type: str, handler, **context: Any) -> dict[str, Any]:
    job_id = secrets.token_urlsafe(12)
    now_iso = datetime.now(UTC).isoformat()
    job_record = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "createdAt": now_iso,
        "updatedAt": now_iso,
        "context": context,
        "result": None,
        "error": None,
    }

    with BACKGROUND_JOB_LOCK:
        BACKGROUND_JOBS[job_id] = job_record

    def _runner() -> None:
        _store_background_job(job_id, {"status": "running", "updatedAt": datetime.now(UTC).isoformat()})
        try:
            try:
                signature = inspect.signature(handler)
                expects_job_id = len(signature.parameters) > 0
            except (TypeError, ValueError):
                expects_job_id = False

            if expects_job_id:
                result = handler(job_id)
            else:
                result = handler()
            _store_background_job(
                job_id,
                {
                    "status": "completed",
                    "updatedAt": datetime.now(UTC).isoformat(),
                    "result": result,
                },
            )
        except Exception as exc:
            _store_background_job(
                job_id,
                {
                    "status": "failed",
                    "updatedAt": datetime.now(UTC).isoformat(),
                    "error": str(exc),
                },
            )

    BACKGROUND_JOB_EXECUTOR.submit(_runner)
    return job_record


def _record_admin_audit_log(
    actor: dict[str, Any],
    action: str,
    entity_type: str,
    entity_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        _supabase_request(
            "/rest/v1/admin_audit_logs?select=*",
            method="POST",
            body={
                "actor_user_id": actor.get("id"),
                "actor_email": actor.get("email"),
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metadata": metadata or {},
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    except Exception:
        # Audit logging should not break the primary admin workflow.
        pass


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/time")
def server_time() -> dict[str, str]:
    return {
        "utc": datetime.now(UTC).isoformat(),
        "timezone": "UTC",
    }


@router.get("/candidate/dashboard")
def candidate_dashboard(request_obj: Request) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate['id'])}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None
    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None
    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)
    booked_slots = [slot for slot in slots if slot.get("status") == "booked"] if isinstance(slots, list) else []

    return {
        "candidate": candidate,
        "authRole": candidate.get("role", "candidate"),
        "targetRole": candidate.get("target_role"),
        "adminOverrideRole": candidate.get("admin_override_role"),
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "stats": {
            "profileCreated": True,
            "resumeUploaded": latest_upload is not None,
            "interviewBooked": len(booked_slots) > 0,
        },
        "latestUpload": latest_upload,
        "bookedSlots": booked_slots,
    }


@router.get("/candidate/interview-slots")
def candidate_interview_slots(request_obj: Request) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)
    application_stage = _get_current_application_stage(candidate)

    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate['id'])}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    sessions = _supabase_request(
        f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate['id'])}&application_stage=eq.{quote(application_stage)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    latest_started = slots[0] if isinstance(slots, list) and slots else None
    latest_session = sessions[0] if isinstance(sessions, list) and sessions else None
    interview_role, _ = _resolve_interview_role(candidate)

    return {
        "slots": slots if isinstance(slots, list) else [],
        "latestStarted": latest_started,
        "latestSession": latest_session,
        "applicationStage": application_stage,
        "interviewPlan": _build_role_specific_interview_plan(interview_role),
    }


@router.post("/candidate/interview-slots")
def candidate_interview_slots_create(request_obj: Request, payload: InterviewSlotPayload) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)
    started_at = datetime.now(UTC).isoformat()

    created_rows = _supabase_request(
        "/rest/v1/interview_slots?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "slot_time": started_at,
            "status": "booked",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None

    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)
    interview_plan = _build_role_specific_interview_plan(interview_role)

    created = created_rows[0] if isinstance(created_rows, list) else created_rows

    return {
        "message": "Interview started",
        "startedAt": started_at,
        "slot": created,
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "interviewPlan": interview_plan,
    }


@router.post("/candidate/interview-session/start")
def candidate_interview_session_start(
    request_obj: Request,
    payload: InterviewSessionStartPayload,
) -> dict[str, Any]:
    if not payload.consentGiven:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent is required before starting an interview session",
        )

    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)
    application_stage = _get_current_application_stage(candidate)

    existing_sessions = _supabase_request(
        f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate['id'])}&application_stage=eq.{quote(application_stage)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    existing_session = existing_sessions[0] if isinstance(existing_sessions, list) and existing_sessions else None
    retry_existing_session = None
    if existing_session:
        existing_status = (existing_session.get("status") or "").strip().lower()

        if existing_status == "in_progress":
            # Fetch job spec for existing in-progress session
            job_specs = _supabase_request(
                f"/rest/v1/job_specifications?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
                method="GET",
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )
            latest_job_spec = None
            if job_specs and isinstance(job_specs, list) and job_specs:
                latest_job_spec_record = job_specs[0]
                if latest_job_spec_record.get("parsed_data") and isinstance(latest_job_spec_record.get("parsed_data"), dict):
                    latest_job_spec = latest_job_spec_record.get("parsed_data")
            
            return {
                "message": "Interview session already in progress",
                "session": existing_session,
                "slot": None,
                "interviewRole": existing_session.get("interview_role") or _resolve_interview_role(candidate)[0],
                "interviewRoleSource": existing_session.get("role_source") or _resolve_interview_role(candidate)[1],
                "interviewPlan": _build_role_specific_interview_plan(
                    existing_session.get("interview_role") or _resolve_interview_role(candidate)[0],
                    latest_job_spec
                ),
                "resumeSummary": candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions.",
                "realtime": None,
                "aiOutputMode": _effective_interview_output_mode(),
            }

        # Allow retry for sessions that ended unsuccessfully.
        if existing_status in {"failed", "terminated"}:
            retry_existing_session = existing_session
            existing_session = None

        if existing_status in {"completed", "scored"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Interview already completed for this application stage",
            )

        if existing_session is None:
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An interview session already exists for this application stage",
            )

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None

    interview_role, role_source = _resolve_interview_role(candidate, inferred_role)
    
    # Fetch the latest job specification if available
    job_specs = _supabase_request(
        f"/rest/v1/job_specifications?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_job_spec = None
    if job_specs and isinstance(job_specs, list) and job_specs:
        latest_job_spec_record = job_specs[0]
        if latest_job_spec_record.get("parsed_data") and isinstance(latest_job_spec_record.get("parsed_data"), dict):
            latest_job_spec = latest_job_spec_record.get("parsed_data")
    
    interview_plan = _build_role_specific_interview_plan(interview_role, latest_job_spec)

    started_at = datetime.now(UTC).isoformat()
    slot_rows = _supabase_request(
        "/rest/v1/interview_slots?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "slot_time": started_at,
            "status": "in_progress",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slot = slot_rows[0] if isinstance(slot_rows, list) else slot_rows

    session_payload = {
        "candidate_id": candidate["id"],
        "application_stage": application_stage,
        "slot_id": slot.get("id") if isinstance(slot, dict) else None,
        "status": "in_progress",
        "interview_role": interview_role,
        "role_source": role_source,
        "provider": settings.llm_provider,
        "started_at": started_at,
        "ended_at": None,
        "consent_given": bool(payload.consentGiven),
        "consent_at": started_at if payload.consentGiven else None,
    }

    if retry_existing_session and isinstance(retry_existing_session, dict) and retry_existing_session.get("id"):
        session_rows = _supabase_request(
            f"/rest/v1/interview_sessions?id=eq.{quote(retry_existing_session['id'])}&select=*",
            method="PATCH",
            body=session_payload,
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    else:
        session_rows = _supabase_request(
            "/rest/v1/interview_sessions?select=*",
            method="POST",
            body=session_payload,
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    session = session_rows[0] if isinstance(session_rows, list) else session_rows

    resume_summary = candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions."
    realtime_response = _create_openai_realtime_session(interview_role, interview_plan, resume_summary)

    scoring_provider_ready = any(
        provider.is_configured()
        for provider in get_llm_provider_chain(settings.llm_provider, settings.llm_provider_fallbacks)
    )

    # Return only public fields; client_secret stays server-side
    realtime_public = None
    if realtime_response:
        realtime_public = {
            "id": realtime_response.get("id"),
            "model": realtime_response.get("model"),
            "expires_at": realtime_response.get("expires_at"),
            # client_secret intentionally omitted
        }

    return {
        "message": "Interview session started",
        "session": session,
        "slot": slot,
        "applicationStage": application_stage,
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "interviewPlan": interview_plan,
        "resumeSummary": resume_summary,
        "realtime": realtime_public,
        "aiOutputMode": _effective_interview_output_mode(),
        "scoringProviderReady": scoring_provider_ready,
    }


@router.get("/candidate/interview-session/{session_id}")
def candidate_interview_session_details(request_obj: Request, session_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    if not _is_valid_uuid(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format",
        )

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        fallback_rows = _supabase_request(
            f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate['id'])}&status=eq.in_progress&select=*&order=created_at.desc&limit=1",
            method="GET",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        if not fallback_rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")
        session_rows = fallback_rows

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    interview_role, role_source = _resolve_interview_role(candidate)
    if session_row.get("interview_role"):
        interview_role = session_row.get("interview_role")
        role_source = session_row.get("role_source") or role_source

    return {
        "session": {
            "id": session_row.get("id"),
            "status": session_row.get("status"),
            "applicationStage": session_row.get("application_stage"),
        },
        "interviewRole": interview_role,
        "interviewRoleSource": role_source,
        "interviewPlan": _build_role_specific_interview_plan(interview_role),
        "resumeSummary": candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions.",
        "aiOutputMode": _effective_interview_output_mode(),
    }


@router.post("/candidate/interview-session/{session_id}/realtime-token")
def candidate_interview_session_realtime_token(request_obj: Request, session_id: str) -> dict[str, Any]:
    if not _is_valid_uuid(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format",
        )

    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        fallback_rows = _supabase_request(
            f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate['id'])}&status=eq.in_progress&select=*&order=created_at.desc&limit=1",
            method="GET",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        if not fallback_rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")
        session_rows = fallback_rows

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    session_status = (session_row.get("status") or "").strip().lower()
    if session_status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Realtime token can only be issued for an in-progress interview session",
        )

    realtime_provider = get_llm_provider_by_name(settings.interview_realtime_provider)
    if not realtime_provider.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Realtime provider is not configured for this deployment",
        )

    interview_role = session_row.get("interview_role") or _resolve_interview_role(candidate)[0]
    job_specs = _supabase_request(
        f"/rest/v1/job_specifications?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_job_spec = None
    if job_specs and isinstance(job_specs, list) and job_specs:
        latest_job_spec_record = job_specs[0]
        if latest_job_spec_record.get("parsed_data") and isinstance(latest_job_spec_record.get("parsed_data"), dict):
            latest_job_spec = latest_job_spec_record.get("parsed_data")

    interview_plan = _build_role_specific_interview_plan(interview_role, latest_job_spec)
    resume_summary = candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions."

    try:
        realtime_payload = realtime_provider.create_realtime_session(
            interview_role=interview_role,
            interview_plan=interview_plan,
            resume_summary=resume_summary,
            include_client_secret=True,
        )
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create realtime session",
        ) from exc

    if not isinstance(realtime_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected realtime provider response",
        )

    client_secret = None
    client_secret_payload = realtime_payload.get("client_secret")
    if isinstance(client_secret_payload, dict):
        maybe_value = client_secret_payload.get("value")
        if isinstance(maybe_value, str) and maybe_value.strip():
            client_secret = maybe_value.strip()

    if not client_secret:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Realtime client secret missing in provider response",
        )

    max_questions = settings.interview_max_questions
    if isinstance(interview_plan.get("realtime"), dict):
        plan_max_questions = interview_plan["realtime"].get("maxQuestions")
        if isinstance(plan_max_questions, int) and plan_max_questions > 0:
            max_questions = plan_max_questions

    return {
        "realtime": {
            "id": realtime_payload.get("id"),
            "model": realtime_payload.get("model") or settings.interview_realtime_model,
            "expiresAt": realtime_payload.get("expires_at"),
            "clientSecret": client_secret,
            "maxQuestions": max_questions,
        }
    }


@router.post("/candidate/interview-session/{session_id}/next-question")
@router.post("/candidate/interview-session/{session_id}/groq-next-question")
def candidate_interview_session_next_question(
    request_obj: Request,
    session_id: str,
    payload: InterviewSessionNextQuestionPayload,
) -> dict[str, Any]:
    if not _is_valid_uuid(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format",
        )

    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        fallback_rows = _supabase_request(
            f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate['id'])}&status=eq.in_progress&select=*&order=created_at.desc&limit=1",
            method="GET",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        if not fallback_rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")
        session_rows = fallback_rows

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    session_status = (session_row.get("status") or "").strip().lower()
    if session_status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview session is not in progress",
        )

    interview_role = session_row.get("interview_role") or _resolve_interview_role(candidate)[0]

    job_specs = _supabase_request(
        f"/rest/v1/job_specifications?candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_job_spec = None
    if job_specs and isinstance(job_specs, list) and job_specs:
        latest_job_spec_record = job_specs[0]
        if latest_job_spec_record.get("parsed_data") and isinstance(latest_job_spec_record.get("parsed_data"), dict):
            latest_job_spec = latest_job_spec_record.get("parsed_data")

    interview_plan = _build_role_specific_interview_plan(interview_role, latest_job_spec)
    max_questions = interview_plan.get("realtime", {}).get("maxQuestions") if isinstance(interview_plan.get("realtime"), dict) else settings.interview_max_questions
    if not isinstance(max_questions, int) or max_questions < 1:
        max_questions = max(1, settings.interview_max_questions)

    transcript_turns = payload.transcriptTurns if isinstance(payload.transcriptTurns, list) else []

    client_questions_asked = payload.questionsAsked if isinstance(payload.questionsAsked, int) and payload.questionsAsked >= 0 else 0
    inferred_questions_asked = _infer_questions_asked_from_transcript(transcript_turns)
    questions_asked = max(client_questions_asked, inferred_questions_asked)
    if questions_asked > max_questions:
        questions_asked = max_questions
    next_question_number = questions_asked + 1
    if next_question_number > max_questions:
        return {
            "completed": True,
            "questionNumber": questions_asked,
            "maxQuestions": max_questions,
        }

    resume_summary = candidate.get("ai_summary") or "Resume summary pending. Ask structured role-fit questions."

    question_text = _generate_next_interview_question_from_leetcode(
        interview_role=interview_role,
        interview_plan=interview_plan,
        resume_summary=resume_summary,
        transcript_turns=transcript_turns,
        next_question_number=next_question_number,
        max_questions=max_questions,
    )

    return {
        "completed": False,
        "question": question_text,
        "questionNumber": next_question_number,
        "maxQuestions": max_questions,
    }


@router.patch("/candidate/interview-session/{session_id}/transcript")
def candidate_interview_session_patch_transcript(
    request_obj: Request,
    session_id: str,
    payload: InterviewSessionTranscriptPatchPayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    if session_row.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview session is not in progress",
        )

    transcript_value = (payload.transcript or "").strip()
    transcript_turns = payload.transcriptTurns if isinstance(payload.transcriptTurns, list) else []
    requested_version = payload.transcriptVersion if isinstance(payload.transcriptVersion, int) else None

    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    existing_artifact = artifact_rows[0] if isinstance(artifact_rows, list) and artifact_rows else None

    score_payload = {}
    if isinstance(existing_artifact, dict) and isinstance(existing_artifact.get("score_payload"), dict):
        score_payload = dict(existing_artifact.get("score_payload") or {})

    existing_version_raw = score_payload.get("transcriptVersion", 0)
    existing_version = existing_version_raw if isinstance(existing_version_raw, int) else 0
    next_version = requested_version if requested_version is not None else existing_version + 1

    if requested_version is not None and requested_version <= existing_version:
        return {
            "message": "Transcript autosave ignored due to stale version",
            "sessionId": session_id,
            "savedAt": datetime.now(UTC).isoformat(),
            "applied": False,
            "transcriptVersion": existing_version,
        }

    score_payload["transcriptTurns"] = transcript_turns
    score_payload["autosavedAt"] = datetime.now(UTC).isoformat()
    score_payload["transcriptVersion"] = next_version

    if existing_artifact and existing_artifact.get("id"):
        _supabase_request(
            f"/rest/v1/interview_artifacts?id=eq.{quote(existing_artifact['id'])}",
            method="PATCH",
            body={
                "transcript": transcript_value,
                "score_payload": score_payload,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    else:
        _supabase_request(
            "/rest/v1/interview_artifacts?select=*",
            method="POST",
            body={
                "session_id": session_id,
                "candidate_id": candidate["id"],
                "transcript": transcript_value,
                "score_payload": score_payload,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    return {
        "message": "Transcript autosaved",
        "sessionId": session_id,
        "savedAt": datetime.now(UTC).isoformat(),
        "applied": True,
        "transcriptVersion": next_version,
    }


@router.post("/candidate/interview-session/{session_id}/terminate")
def candidate_interview_session_terminate(
    request_obj: Request,
    session_id: str,
    payload: InterviewSessionTerminatePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    if session_row.get("status") != "in_progress":
        return {
            "message": "Interview session already finalized",
            "sessionId": session_id,
            "status": session_row.get("status"),
        }

    reason = (payload.reason or "").strip().lower()
    allowed_reasons = {"fullscreen_exit", "tab_leave", "route_leave", "network_failure", "manual_end"}
    if reason not in allowed_reasons:
        reason = "manual_end"

    ended_at = datetime.now(UTC).isoformat()
    duration_seconds = payload.durationSeconds if isinstance(payload.durationSeconds, int) else None

    _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}",
        method="PATCH",
        body={
            "status": "failed",
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    slot_id = session_row.get("slot_id") if isinstance(session_row, dict) else None
    if slot_id:
        _supabase_request(
            f"/rest/v1/interview_slots?id=eq.{quote(slot_id)}",
            method="PATCH",
            body={"status": "failed"},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    transcript_value = (payload.transcript or "").strip()
    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    existing_artifact = artifact_rows[0] if isinstance(artifact_rows, list) and artifact_rows else None

    if existing_artifact and existing_artifact.get("id"):
        existing_score = existing_artifact.get("score_payload") if isinstance(existing_artifact.get("score_payload"), dict) else {}
        score_payload = {
            **existing_score,
            "terminationReason": reason,
            "terminatedAt": ended_at,
        }
        _supabase_request(
            f"/rest/v1/interview_artifacts?id=eq.{quote(existing_artifact['id'])}",
            method="PATCH",
            body={
                "transcript": transcript_value or existing_artifact.get("transcript"),
                "score_payload": score_payload,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    elif transcript_value:
        _supabase_request(
            "/rest/v1/interview_artifacts?select=*",
            method="POST",
            body={
                "session_id": session_id,
                "candidate_id": candidate["id"],
                "transcript": transcript_value,
                "score_payload": {
                    "terminationReason": reason,
                    "terminatedAt": ended_at,
                },
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    _delete_interview_upload_nonces_for_session(session_id, candidate.get("id"))

    return {
        "message": "Interview session terminated",
        "sessionId": session_id,
        "reason": reason,
        "endedAt": ended_at,
    }


@router.post("/candidate/interview-session/{session_id}/complete")
def candidate_interview_session_complete(
    request_obj: Request,
    session_id: str,
    payload: InterviewSessionCompletePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    
    # SECURITY FIX #2: Verify consent before accepting completion
    # Transcripts and media must only persist if explicit consent was given
    if not session_row.get("consent_given"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot complete interview without prior explicit consent"
        )
    
    # Idempotent completion for retries after successful finalize.
    if session_row.get("status") == "completed":
        return {
            "message": "Interview session already completed",
            "sessionId": session_id,
            "status": "completed",
            "endedAt": session_row.get("ended_at"),
        }

    if session_row.get("status") in {"failed", "terminated"}:
        return {
            "message": "Interview session already finalized",
            "sessionId": session_id,
            "status": session_row.get("status"),
            "endedAt": session_row.get("ended_at"),
        }

    # SECURITY FIX #3: Require session-bound single-use upload nonce for media artifacts
    if payload.videoPath:
        if not payload.videoUploadNonce:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing upload nonce for video artifact",
            )

        nonce_payload = _get_interview_upload_nonce(payload.videoUploadNonce, candidate["id"], session_id, "video")
        now_dt = datetime.now(UTC)
        expires_at = _parse_utc_datetime((nonce_payload or {}).get("expires_at"))
        if (
            not isinstance(nonce_payload, dict)
            or nonce_payload.get("used")
            or not expires_at
            or expires_at < now_dt
            or nonce_payload.get("path") != payload.videoPath
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired upload nonce for video artifact",
            )

        _mark_interview_upload_nonce_used(payload.videoUploadNonce)

    if payload.audioPath:
        if not payload.audioUploadNonce:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing upload nonce for audio artifact",
            )

        audio_nonce_payload = _get_interview_upload_nonce(payload.audioUploadNonce, candidate["id"], session_id, "audio")
        now_dt = datetime.now(UTC)
        audio_expires_at = _parse_utc_datetime((audio_nonce_payload or {}).get("expires_at"))
        if (
            not isinstance(audio_nonce_payload, dict)
            or audio_nonce_payload.get("used")
            or not audio_expires_at
            or audio_expires_at < now_dt
            or audio_nonce_payload.get("path") != payload.audioPath
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired upload nonce for audio artifact",
            )

        _mark_interview_upload_nonce_used(payload.audioUploadNonce)
    
    ended_at = datetime.now(UTC).isoformat()
    duration_seconds = payload.durationSeconds if isinstance(payload.durationSeconds, int) else None

    _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}",
        method="PATCH",
        body={
            "status": "completed",
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    slot_id = session_row.get("slot_id") if isinstance(session_row, dict) else None
    if slot_id:
        _supabase_request(
            f"/rest/v1/interview_slots?id=eq.{quote(slot_id)}",
            method="PATCH",
            body={"status": "completed"},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    resolved_role = session_row.get("interview_role") if isinstance(session_row, dict) else None
    interview_role = resolved_role or "General Candidate"
    interview_plan = _build_role_specific_interview_plan(interview_role)
    total_questions = len(interview_plan.get("questions") or [])

    incoming_score_payload = payload.scorePayload if isinstance(payload.scorePayload, dict) else {}
    transcript_turns = incoming_score_payload.get("transcriptTurns") if isinstance(incoming_score_payload.get("transcriptTurns"), list) else []
    resume_score = candidate.get("ai_score") if isinstance(candidate.get("ai_score"), int) else 70
    scoring_status = "completed"
    scoring_error = None
    scoring = None
    try:
        scoring = _build_interview_scoring_rubric(
            payload.transcript,
            transcript_turns,
            duration_seconds,
            total_questions,
            resume_score,
            interview_role,
            interview_plan,
        )
    except Exception as exc:
        scoring_status = "pending"
        scoring_error = _friendly_scoring_error_message(str(exc))

    final_score_payload = {
        **incoming_score_payload,
        "role": interview_role or incoming_score_payload.get("role") or "General Candidate",
        "resumeScore": resume_score,
        "scoringStatus": scoring_status,
        "queuedAt": datetime.now(UTC).isoformat() if scoring_status == "pending" else None,
        "scoringError": scoring_error,
        "evaluationVersion": "phase3-scoring-pending-v1" if scoring_status == "pending" else (scoring.get("version", "phase3-scoring-v1") if isinstance(scoring, dict) else "phase3-scoring-v1"),
    }
    if isinstance(scoring, dict):
        final_score_payload.update(
            {
                "overallScore": scoring.get("overallScore"),
                "answeredCount": scoring.get("answeredCount"),
                "totalQuestions": scoring.get("totalQuestions"),
                "scoringRubric": scoring,
            }
        )

    existing_artifacts = _supabase_request(
        f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    existing_artifact = existing_artifacts[0] if isinstance(existing_artifacts, list) and existing_artifacts else None

    if existing_artifact and existing_artifact.get("id"):
        artifact_rows = _supabase_request(
            f"/rest/v1/interview_artifacts?id=eq.{quote(existing_artifact['id'])}&select=*",
            method="PATCH",
            body={
                "audio_path": payload.audioPath,
                "audio_url": payload.audioUrl,
                "video_path": payload.videoPath,
                "video_url": payload.videoUrl,
                "transcript": payload.transcript,
                "score_payload": final_score_payload,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
    else:
        artifact_rows = _supabase_request(
            "/rest/v1/interview_artifacts?select=*",
            method="POST",
            body={
                "session_id": session_id,
                "candidate_id": candidate["id"],
                "audio_path": payload.audioPath,
                "audio_url": payload.audioUrl,
                "video_path": payload.videoPath,
                "video_url": payload.videoUrl,
                "transcript": payload.transcript,
                "score_payload": final_score_payload,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    # PostgREST may return an empty body for insert unless representation is requested.
    # Re-fetch latest artifact for this session to guarantee a stable response shape.
    if not artifact_rows:
        artifact_rows = _supabase_request(
            f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
            method="GET",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

    artifact = artifact_rows[0] if isinstance(artifact_rows, list) and artifact_rows else artifact_rows
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Interview completed but artifact could not be loaded",
        )

    # Best-effort cleanup of any remaining nonce rows for this session
    _delete_interview_upload_nonces_for_session(session_id, candidate.get("id"))

    return {
        "message": "Interview session completed" if scoring_status == "completed" else "Interview session completed; scoring queued",
        "sessionId": session_id,
        "artifact": artifact,
        "endedAt": ended_at,
        "scoringStatus": scoring_status,
    }


@router.post("/candidate/profile-upload")
def candidate_profile_upload(request_obj: Request, payload: ProfileUploadPayload) -> dict[str, object]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]
    candidate = _get_or_create_candidate(user)

    uploaded_rows = _supabase_request(
        "/rest/v1/profile_uploads?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "user_id": user_id,
            "file_name": payload.filename,
            "file_path": payload.filePath,
            "file_url": payload.fileUrl,
            "mime_type": payload.type,
            "file_size": payload.size,
            "status": "uploaded",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    target_role = _normalize_role_value(payload.targetRole)
    if target_role:
        _supabase_request(
            f"/rest/v1/candidates?id=eq.{quote(candidate['id'])}",
            method="PATCH",
            body={"target_role": target_role},
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        candidate["target_role"] = target_role

    uploaded = uploaded_rows[0] if isinstance(uploaded_rows, list) else uploaded_rows

    return {
        "message": "Profile upload saved to Supabase",
        "candidate": candidate,
        "interviewRole": _resolve_interview_role(candidate)[0],
        "upload": uploaded,
        "receivedAt": datetime.now(UTC).isoformat(),
        "submittedAt": payload.submittedAt,
    }


@router.post("/candidate/job-specification-upload")
def candidate_job_specification_upload(request_obj: Request, payload: JobSpecificationPayload) -> dict[str, object]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]
    candidate = _get_or_create_candidate(user)

    uploaded_rows = _supabase_request(
        "/rest/v1/job_specifications?select=*",
        method="POST",
        body={
            "candidate_id": candidate["id"],
            "user_id": user_id,
            "file_name": payload.filename,
            "file_path": payload.filePath,
            "file_url": payload.fileUrl,
            "mime_type": payload.type,
            "file_size": payload.size,
            "status": "uploaded",
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    uploaded = uploaded_rows[0] if isinstance(uploaded_rows, list) else uploaded_rows
    job_spec_id = uploaded.get("id")

    # Extract and parse the job specification asynchronously
    def parse_job_spec_async():
        try:
            file_url = payload.fileUrl
            extracted_text = ""
            
            if isinstance(file_url, str) and file_url:
                try:
                    extracted_text = _extract_pdf_text(_download_url_bytes(file_url))
                except Exception:
                    extracted_text = ""
            
            if not extracted_text.strip():
                raise ValueError("Could not extract text from job specification PDF")
            
            parsed_data = _parse_job_specification(extracted_text)
            
            # Update the job spec record with parsed data and raw text
            _supabase_request(
                f"/rest/v1/job_specifications?id=eq.{quote(job_spec_id)}",
                method="PATCH",
                body={
                    "raw_text": extracted_text,
                    "parsed_data": parsed_data,
                    "status": "parsed",
                },
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )
        except Exception as e:
            print(f"Error parsing job specification {job_spec_id}: {str(e)}")
            _supabase_request(
                f"/rest/v1/job_specifications?id=eq.{quote(job_spec_id)}",
                method="PATCH",
                body={"status": "error"},
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )

    # Run parsing in background thread
    thread = threading.Thread(target=parse_job_spec_async, daemon=True)
    thread.start()

    return {
        "message": "Job specification uploaded and queued for parsing",
        "candidate": candidate,
        "upload": uploaded,
        "jobSpecId": job_spec_id,
        "receivedAt": datetime.now(UTC).isoformat(),
        "submittedAt": payload.submittedAt,
    }
def candidate_interview_session_retry_scoring(request_obj: Request, session_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    candidate = _get_or_create_candidate(user)

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    if session_row.get("status") != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scoring retry is only allowed for completed sessions")

    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not artifact_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview artifact not found")

    artifact = artifact_rows[0] if isinstance(artifact_rows, list) else artifact_rows
    transcript_text = artifact.get("transcript") if isinstance(artifact, dict) else None
    score_payload = artifact.get("score_payload") if isinstance(artifact, dict) and isinstance(artifact.get("score_payload"), dict) else {}
    transcript_turns = score_payload.get("transcriptTurns") if isinstance(score_payload.get("transcriptTurns"), list) else []

    interview_role = session_row.get("interview_role") or _resolve_interview_role(candidate)[0]
    interview_plan = _build_role_specific_interview_plan(interview_role)
    total_questions = len(interview_plan.get("questions") or [])
    resume_score = candidate.get("ai_score") if isinstance(candidate.get("ai_score"), int) else 70
    duration_seconds = session_row.get("duration_seconds") if isinstance(session_row.get("duration_seconds"), int) else None

    try:
        scoring = _build_interview_scoring_rubric(
            transcript_text,
            transcript_turns,
            duration_seconds,
            total_questions,
            resume_score,
            interview_role,
            interview_plan,
        )
    except Exception as exc:
        raise _to_scoring_provider_http_exception(exc) from exc

    updated_payload = {
        **score_payload,
        "overallScore": scoring.get("overallScore"),
        "answeredCount": scoring.get("answeredCount"),
        "totalQuestions": scoring.get("totalQuestions"),
        "role": interview_role,
        "resumeScore": resume_score,
        "scoringRubric": scoring,
        "scoringStatus": "completed",
        "scoringError": None,
        "queuedAt": None,
        "scoredAt": datetime.now(UTC).isoformat(),
        "evaluationVersion": scoring.get("version", "phase3-scoring-v1"),
    }

    _supabase_request(
        f"/rest/v1/interview_artifacts?id=eq.{quote(artifact['id'])}",
        method="PATCH",
        body={"score_payload": updated_payload},
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    return {
        "message": "Interview scoring completed",
        "sessionId": session_id,
        "artifactId": artifact.get("id"),
        "overallScore": scoring.get("overallScore"),
    }


@router.post("/admin/interview-session/{session_id}/score/retry")
def admin_interview_session_retry_scoring(request_obj: Request, session_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    if session_row.get("status") != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scoring retry is only allowed for completed sessions")

    candidate_id = session_row.get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session candidate context is missing")

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    candidate = candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows

    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not artifact_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview artifact not found")

    artifact = artifact_rows[0] if isinstance(artifact_rows, list) else artifact_rows
    transcript_text = artifact.get("transcript") if isinstance(artifact, dict) else None
    score_payload = artifact.get("score_payload") if isinstance(artifact, dict) and isinstance(artifact.get("score_payload"), dict) else {}
    transcript_turns = score_payload.get("transcriptTurns") if isinstance(score_payload.get("transcriptTurns"), list) else []

    interview_role = session_row.get("interview_role") or _resolve_interview_role(candidate)[0]
    interview_plan = _build_role_specific_interview_plan(interview_role)
    total_questions = len(interview_plan.get("questions") or [])
    resume_score = candidate.get("ai_score") if isinstance(candidate.get("ai_score"), int) else 70
    duration_seconds = session_row.get("duration_seconds") if isinstance(session_row.get("duration_seconds"), int) else None

    try:
        scoring = _build_interview_scoring_rubric(
            transcript_text,
            transcript_turns,
            duration_seconds,
            total_questions,
            resume_score,
            interview_role,
            interview_plan,
        )
    except Exception as exc:
        raise _to_scoring_provider_http_exception(exc) from exc

    updated_payload = {
        **score_payload,
        "overallScore": scoring.get("overallScore"),
        "answeredCount": scoring.get("answeredCount"),
        "totalQuestions": scoring.get("totalQuestions"),
        "role": interview_role,
        "resumeScore": resume_score,
        "scoringRubric": scoring,
        "scoringStatus": "completed",
        "scoringError": None,
        "queuedAt": None,
        "scoredAt": datetime.now(UTC).isoformat(),
        "evaluationVersion": scoring.get("version", "phase3-scoring-v1"),
    }

    _supabase_request(
        f"/rest/v1/interview_artifacts?id=eq.{quote(artifact['id'])}",
        method="PATCH",
        body={"score_payload": updated_payload},
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    return {
        "message": "Interview scoring completed",
        "sessionId": session_id,
        "artifactId": artifact.get("id"),
        "overallScore": scoring.get("overallScore"),
    }


@router.post("/candidate/storage/signed-upload")
def candidate_storage_signed_upload(request_obj: Request, payload: SignedUploadPayload) -> dict[str, str]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]

    if not payload.path or not payload.path.startswith(f"{user_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload path is not allowed for this user",
        )

    try:
        return _build_storage_signed_upload_url(payload.path)
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to sign upload URL: {exc}",
        ) from exc


@router.post("/candidate/storage/signed-interview-upload")
def candidate_storage_signed_interview_upload(request_obj: Request, payload: SignedInterviewUploadPayload) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    user_id = user["id"]
    candidate = _get_or_create_candidate(user)

    session_id = (payload.sessionId or "").strip()
    file_type = (payload.fileType or "").strip().lower()
    extension = (payload.extension or "webm").strip().lower()

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sessionId is required",
        )

    if not _is_valid_uuid(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sessionId format",
        )

    if file_type not in {"video", "audio"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fileType must be either 'video' or 'audio'",
        )

    if not re.fullmatch(r"[a-z0-9]{2,8}", extension):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file extension",
        )

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&candidate_id=eq.{quote(candidate['id'])}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview session not found for this candidate",
        )

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    if session_row.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview session is not in progress",
        )

    if not session_row.get("consent_given"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Consent is required before uploading interview media",
        )

    # Bind upload URL to candidate + session + file_type, with server-controlled path
    timestamp = int(time.time() * 1000)
    storage_path = f"{user_id}/{session_id}/{file_type}-{timestamp}.{extension}"

    # Revoke prior unused nonces for this exact session/file_type pair
    _revoke_interview_upload_nonces(candidate["id"], session_id, file_type)

    try:
        signed = _build_storage_signed_upload_url(storage_path, bucket_id="interview-media", is_public=False)

        upload_nonce = secrets.token_urlsafe(32)
        _supabase_request(
            "/rest/v1/interview_upload_nonces?select=*",
            method="POST",
            body={
                "id": upload_nonce,
                "candidate_id": candidate["id"],
                "session_id": session_id,
                "user_id": user_id,
                "file_type": file_type,
                "path": storage_path,
                "used": False,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

        return {
            **signed,
            "uploadNonce": upload_nonce,
            "expiresIn": 300,
            "sessionId": session_id,
            "fileType": file_type,
        }
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to sign interview upload URL: {exc}",
        ) from exc


@router.get("/admin/candidates")
def admin_candidates(
    request_obj: Request,
    search: str | None = Query(None),
    stage: str | None = Query(None),
    minScore: int | None = Query(None),
    maxScore: int | None = Query(None),
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    candidates = _supabase_request(
        "/rest/v1/candidates?select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    uploads = _supabase_request(
        "/rest/v1/profile_uploads?select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    uploads_by_candidate: dict[str, list[dict[str, Any]]] = {}
    if isinstance(uploads, list):
        for item in uploads:
            cid = item.get("candidate_id")
            if not cid:
                continue
            uploads_by_candidate.setdefault(cid, []).append(item)

    artifacts = _supabase_request(
        "/rest/v1/interview_artifacts?select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    artifact_score_by_candidate: dict[str, int] = {}
    if isinstance(artifacts, list):
        for artifact in artifacts:
            candidate_id = artifact.get("candidate_id")
            score_payload = artifact.get("score_payload") if isinstance(artifact.get("score_payload"), dict) else {}
            overall_score = score_payload.get("overallScore")
            scoring_status = score_payload.get("scoringStatus")
            if (
                candidate_id
                and isinstance(overall_score, int)
                and candidate_id not in artifact_score_by_candidate
                and scoring_status != "pending"
            ):
                artifact_score_by_candidate[candidate_id] = overall_score

    response_candidates = []
    for candidate in candidates if isinstance(candidates, list) else []:
        candidate_uploads = uploads_by_candidate.get(candidate["id"], [])
        latest_upload = candidate_uploads[0] if candidate_uploads else None
        ai_score = candidate.get("ai_score")
        final_score = artifact_score_by_candidate.get(candidate["id"])
        interview_role, role_source = _resolve_interview_role(candidate)
        current_score = final_score if isinstance(final_score, int) else (ai_score if isinstance(ai_score, int) else 70 + min(len(candidate_uploads) * 5, 25))
        current_stage = candidate.get("current_stage")
        if not current_stage:
            current_stage = "profile_pending"
        candidate_name = candidate.get("full_name", "Candidate")
        
        # Apply filters
        if search:
            search_lower = search.lower()
            name_match = search_lower in candidate_name.lower()
            skills_match = False
            if isinstance(candidate.get("ai_skills"), list):
                skills_match = any(search_lower in str(skill).lower() for skill in candidate.get("ai_skills", []))
            if not (name_match or skills_match):
                continue
        
        if stage and current_stage != stage:
            continue
        
        if minScore is not None and current_score < minScore:
            continue
        
        if maxScore is not None and current_score > maxScore:
            continue
        
        response_candidates.append(
            {
                "id": candidate["id"],
                "name": candidate_name,
                "role": interview_role,
                "authRole": candidate.get("role", "candidate"),
                "targetRole": candidate.get("target_role"),
                "adminOverrideRole": candidate.get("admin_override_role"),
                "interviewRoleSource": role_source,
                "stage": current_stage,
                "score": current_score,
                "latestUpload": latest_upload,
            }
        )

    return {"candidates": response_candidates}


@router.get("/admin/candidates/{candidate_id}")
def admin_candidate_details(request_obj: Request, candidate_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate = candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows
    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate_id)}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?candidate_id=eq.{quote(candidate_id)}&select=*&order=started_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    artifacts_by_session: dict[str, dict[str, Any]] = {}
    for artifact in artifact_rows if isinstance(artifact_rows, list) else []:
        session_id = artifact.get("session_id")
        if not session_id or session_id in artifacts_by_session:
            continue
        artifacts_by_session[session_id] = artifact

    interview_sessions: list[dict[str, Any]] = []
    for session in session_rows if isinstance(session_rows, list) else []:
        artifact = artifacts_by_session.get(session.get("id")) if isinstance(session, dict) else None
        score_payload = artifact.get("score_payload") if isinstance(artifact, dict) and isinstance(artifact.get("score_payload"), dict) else {}
        scoring_rubric = score_payload.get("scoringRubric") if isinstance(score_payload.get("scoringRubric"), dict) else {}
        rubric_overall = scoring_rubric.get("overallScore")
        if not isinstance(rubric_overall, int):
            rubric_overall = score_payload.get("overallScore")

        interview_sessions.append(
            {
                "id": session.get("id"),
                "status": session.get("status"),
                "applicationStage": session.get("application_stage"),
                "startedAt": session.get("started_at"),
                "endedAt": session.get("ended_at"),
                "durationSeconds": session.get("duration_seconds"),
                "provider": session.get("provider"),
                "terminationReason": score_payload.get("terminationReason"),
                "scoringStatus": score_payload.get("scoringStatus") or ("completed" if isinstance(rubric_overall, int) else "pending"),
                "scoringError": score_payload.get("scoringError"),
                "rubricOverall": rubric_overall if isinstance(rubric_overall, int) else None,
            }
        )

    sorted_sessions = sorted(
        interview_sessions,
        key=lambda item: str(item.get("startedAt") or item.get("endedAt") or ""),
    )
    previous_score: int | None = None
    for session in sorted_sessions:
        current_score = session.get("rubricOverall")
        if isinstance(current_score, int) and isinstance(previous_score, int):
            session["rubricDelta"] = current_score - previous_score
        else:
            session["rubricDelta"] = None
        if isinstance(current_score, int):
            previous_score = current_score

    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None
    inferred_role = None
    if latest_upload and latest_upload.get("file_url"):
        try:
            extracted_text = _extract_pdf_text(_download_url_bytes(latest_upload["file_url"]))
            inferred_role = _infer_interview_role_from_resume_text(extracted_text)
        except Exception:
            inferred_role = None

    if latest_upload and not candidate.get("ai_summary"):
        analysis = _build_resume_analysis(candidate, latest_upload)
        _persist_candidate_analysis(candidate["id"], analysis)
        candidate = {**candidate, **analysis}

    return _candidate_detail_payload(
        candidate,
        latest_upload,
        slots if isinstance(slots, list) else [],
        interview_sessions,
        inferred_role,
    )


@router.post("/admin/candidates/{candidate_id}/interview-role")
@router.patch("/admin/candidates/{candidate_id}/interview-role")
def admin_update_candidate_interview_role(
    request_obj: Request,
    candidate_id: str,
    payload: AdminInterviewRolePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    target_role = _normalize_role_value(payload.targetRole)
    admin_override_role = _normalize_role_value(payload.adminOverrideRole)

    _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
        method="PATCH",
        body={
            "target_role": target_role,
            "admin_override_role": admin_override_role,
        },
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    _record_admin_audit_log(
        user,
        "candidate_interview_role_updated",
        "candidate",
        candidate_id,
        {
            "targetRole": target_role,
            "adminOverrideRole": admin_override_role,
        },
    )

    refreshed_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    refreshed_candidate = refreshed_rows[0] if isinstance(refreshed_rows, list) else refreshed_rows

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate_id)}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    return _candidate_detail_payload(refreshed_candidate, latest_upload, slots if isinstance(slots, list) else [], [])


@router.post("/admin/candidates/{candidate_id}/stage")
@router.patch("/admin/candidates/{candidate_id}/stage")
def admin_update_candidate_stage(
    request_obj: Request,
    candidate_id: str,
    payload: AdminCandidateStagePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    if payload.stage not in VALID_CANDIDATE_STAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage. Valid stages: {', '.join(VALID_CANDIDATE_STAGES)}",
        )

    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
        method="PATCH",
        body={"current_stage": payload.stage},
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    _record_admin_audit_log(
        user,
        "candidate_stage_updated",
        "candidate",
        candidate_id,
        {"stage": payload.stage},
    )

    refreshed_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    refreshed_candidate = refreshed_rows[0] if isinstance(refreshed_rows, list) else refreshed_rows

    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    slots = _supabase_request(
        f"/rest/v1/interview_slots?candidate_id=eq.{quote(candidate_id)}&select=*&order=slot_time.asc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    return _candidate_detail_payload(refreshed_candidate, latest_upload, slots if isinstance(slots, list) else [], [])


@router.get("/admin/interview-session/{session_id}")
def admin_interview_session_details(request_obj: Request, session_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    session_rows = _supabase_request(
        f"/rest/v1/interview_sessions?id=eq.{quote(session_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found")

    session_row = session_rows[0] if isinstance(session_rows, list) else session_rows
    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?session_id=eq.{quote(session_id)}&select=*&order=created_at.desc&limit=1",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    artifact = artifact_rows[0] if isinstance(artifact_rows, list) and artifact_rows else None
    audio_signed = None
    video_signed = None
    if artifact:
        if artifact.get("audio_path"):
            try:
                audio_signed = _build_storage_signed_read_url(artifact["audio_path"], "interview-media")
            except Exception:
                audio_signed = None
        if artifact.get("video_path"):
            try:
                video_signed = _build_storage_signed_read_url(artifact["video_path"], "interview-media")
            except Exception:
                video_signed = None

    return {
        "session": session_row,
        "artifact": artifact,
        "audioSignedUrl": audio_signed,
        "videoSignedUrl": video_signed,
    }


@router.post("/admin/candidates/{candidate_id}/hiring-outcome")
def admin_record_hiring_outcome(
    request_obj: Request,
    candidate_id: str,
    payload: AdminHiringOutcomePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    outcome = _normalize_hiring_outcome(payload.outcome)
    if not outcome:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Outcome must be either 'hired' or 'not_hired'",
        )

    retention_days = payload.retentionDays if isinstance(payload.retentionDays, int) else 30
    if retention_days < 0 or retention_days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="retentionDays must be between 0 and 365",
        )

    now_iso = datetime.now(UTC).isoformat()
    expires_at = (datetime.now(UTC) + timedelta(days=retention_days)).isoformat()

    artifact_rows = _supabase_request(
        f"/rest/v1/interview_artifacts?candidate_id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    updated_count = 0
    for artifact in artifact_rows if isinstance(artifact_rows, list) else []:
        artifact_id = artifact.get("id")
        if not artifact_id:
            continue
        _supabase_request(
            f"/rest/v1/interview_artifacts?id=eq.{quote(artifact_id)}",
            method="PATCH",
            body={
                "hiring_outcome": outcome,
                "outcome_at": now_iso,
                "expires_at": expires_at,
                "archived_at": now_iso,
            },
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )
        updated_count += 1

    return {
        "message": "Hiring outcome recorded and interview artifact retention scheduled",
        "candidateId": candidate_id,
        "outcome": outcome,
        "retentionDays": retention_days,
        "expiresAt": expires_at,
        "updatedArtifacts": updated_count,
    }


@router.post("/admin/candidates/bulk-stage")
@router.patch("/admin/candidates/bulk-stage")
def admin_bulk_update_candidate_stage(
    request_obj: Request,
    payload: AdminBulkCandidateStagePayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    if payload.stage not in VALID_CANDIDATE_STAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage. Valid stages: {', '.join(VALID_CANDIDATE_STAGES)}",
        )

    candidate_ids = [candidate_id for candidate_id in payload.candidateIds if isinstance(candidate_id, str) and candidate_id.strip()]
    if not candidate_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one candidate id is required")

    unique_candidate_ids = list(dict.fromkeys(candidate_ids))

    if payload.runInBackground:
        _record_admin_audit_log(
            user,
            "candidate_stage_bulk_update_queued",
            "candidate",
            None,
            {"candidateCount": len(unique_candidate_ids), "stage": payload.stage},
        )
        job = _submit_background_job(
            "candidate_bulk_stage_update",
            lambda job_id: _admin_bulk_update_candidate_stage_job(
                payload.stage,
                unique_candidate_ids,
                user,
                job_id=job_id,
            ),
            candidateCount=len(unique_candidate_ids),
            stage=payload.stage,
            requestedBy=user.get("id"),
        )
        return {"jobId": job["id"], "status": job["status"], "type": job["type"]}

    return _admin_bulk_update_candidate_stage_job(payload.stage, unique_candidate_ids, user, job_id=None)


def _admin_bulk_update_candidate_stage_job(
    stage: str,
    candidate_ids: list[str],
    actor: dict[str, Any],
    job_id: str | None,
) -> dict[str, Any]:
    missing_candidate_ids: list[str] = []
    updated_candidates: list[dict[str, Any]] = []

    total = len(candidate_ids)
    for index, candidate_id in enumerate(candidate_ids, start=1):
        candidate_rows = _supabase_request(
            f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
            method="GET",
            bearer_token=settings.supabase_service_role_key,
            use_service_role=True,
        )

        if not candidate_rows:
            missing_candidate_ids.append(candidate_id)
        else:
            existing_candidate = candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows

            _supabase_request(
                f"/rest/v1/candidates?id=eq.{quote(candidate_id)}",
                method="PATCH",
                body={"current_stage": stage},
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )

            updated_candidates.append(_admin_refetch_candidate_detail(candidate_id))

        if job_id:
            _store_background_job(
                job_id,
                {
                    "updatedAt": datetime.now(UTC).isoformat(),
                    "progress": {
                        "processed": index,
                        "total": total,
                        "percent": int((index / total) * 100) if total else 100,
                    },
                },
            )

    if not updated_candidates and missing_candidate_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No candidates were found to update")

    _record_admin_audit_log(
        actor,
        "candidate_stage_bulk_updated",
        "candidate",
        None,
        {
            "candidateCount": len(updated_candidates),
            "missingCount": len(missing_candidate_ids),
            "stage": stage,
        },
    )

    return {
        "updatedCount": len(updated_candidates),
        "missingCandidateIds": missing_candidate_ids,
        "updatedCandidates": updated_candidates,
        "stage": stage,
    }


@router.post("/admin/interview-artifacts/cleanup")
def admin_cleanup_expired_interview_artifacts(
    request_obj: Request,
    payload: AdminCleanupArtifactsPayload,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    limit = payload.limit if isinstance(payload.limit, int) else 100
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 500",
        )

    if payload.runInBackground:
        _record_admin_audit_log(
            user,
            "interview_artifacts_cleanup_queued",
            "interview_artifact",
            None,
            {"limit": limit},
        )
        job = _submit_background_job(
            "cleanup_expired_interview_artifacts",
            lambda: _admin_cleanup_expired_interview_artifacts(limit=limit, actor=user),
            limit=limit,
            requestedBy=user.get("id"),
        )
        return {"jobId": job["id"], "status": job["status"], "type": job["type"]}

    return _admin_cleanup_expired_interview_artifacts(limit=limit, actor=user)


def _admin_cleanup_expired_interview_artifacts(limit: int, actor: dict[str, Any] | None = None) -> dict[str, Any]:

    now_iso = datetime.now(UTC).isoformat()
    expired_artifacts = _supabase_request(
        f"/rest/v1/interview_artifacts?select=*&expires_at=lt.{quote(now_iso)}&order=expires_at.asc&limit={limit}",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    deleted_rows = 0
    deleted_storage = 0
    cleanup_errors: list[dict[str, str]] = []

    for artifact in expired_artifacts if isinstance(expired_artifacts, list) else []:
        artifact_id = artifact.get("id")
        if not artifact_id:
            continue

        try:
            storage_delete_failed = False
            for media_path in (artifact.get("audio_path"), artifact.get("video_path")):
                if not media_path:
                    continue
                try:
                    _delete_storage_object(media_path, "interview-media")
                    deleted_storage += 1
                except Exception as exc:
                    storage_delete_failed = True
                    cleanup_errors.append({
                        "artifactId": str(artifact_id),
                        "error": f"storage delete failed: {exc}",
                    })
                    break

            if storage_delete_failed:
                continue

            _supabase_request(
                "/rest/v1/interview_artifact_deletion_log?select=*",
                method="POST",
                body={
                    "artifact_id": artifact_id,
                    "candidate_id": artifact.get("candidate_id"),
                    "deleted_reason": "retention_expired",
                    "deleted_by": actor.get("id") if actor else None,
                },
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )

            _supabase_request(
                f"/rest/v1/interview_artifacts?id=eq.{quote(artifact_id)}",
                method="DELETE",
                bearer_token=settings.supabase_service_role_key,
                use_service_role=True,
            )
            deleted_rows += 1
        except Exception as exc:
            cleanup_errors.append({
                "artifactId": str(artifact_id),
                "error": str(exc),
            })

    _record_admin_audit_log(
        actor or {},
        "interview_artifacts_cleanup_completed",
        "interview_artifact",
        None,
        {
            "evaluated": len(expired_artifacts) if isinstance(expired_artifacts, list) else 0,
            "deletedArtifacts": deleted_rows,
            "deletedStorageObjects": deleted_storage,
        },
    )

    _record_admin_audit_log(
        actor or {},
        "interview_artifacts_cleanup_completed",
        "interview_artifact",
        None,
        {
            "evaluated": len(expired_artifacts) if isinstance(expired_artifacts, list) else 0,
            "deletedArtifacts": deleted_rows,
            "deletedStorageObjects": deleted_storage,
        },
    )

    return {
        "message": "Expired interview artifacts cleanup completed",
        "evaluated": len(expired_artifacts) if isinstance(expired_artifacts, list) else 0,
        "deletedArtifacts": deleted_rows,
        "deletedStorageObjects": deleted_storage,
        "errors": cleanup_errors,
    }


@router.post("/admin/analyze-resume/{candidate_id}")
def admin_analyze_resume(request_obj: Request, candidate_id: str, payload: ResumeAnalysisPayload) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    if payload.runInBackground:
        _record_admin_audit_log(
            user,
            "resume_analysis_queued",
            "candidate",
            candidate_id,
            {"force": payload.force},
        )
        job = _submit_background_job(
            "resume_analysis",
            lambda: _admin_analyze_resume(candidate_id=candidate_id, force=payload.force, actor=user),
            candidateId=candidate_id,
            force=payload.force,
        )
        return {"jobId": job["id"], "status": job["status"], "type": job["type"]}

    return _admin_analyze_resume(candidate_id=candidate_id, force=payload.force, actor=user)


def _admin_analyze_resume(candidate_id: str, force: bool, actor: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate_rows = _supabase_request(
        f"/rest/v1/candidates?id=eq.{quote(candidate_id)}&select=*",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate = candidate_rows[0] if isinstance(candidate_rows, list) else candidate_rows
    uploads = _supabase_request(
        f"/rest/v1/profile_uploads?candidate_id=eq.{quote(candidate_id)}&select=*&order=created_at.desc",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )
    latest_upload = uploads[0] if isinstance(uploads, list) and uploads else None

    if not latest_upload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No resume upload found for this candidate")

    if not force and candidate.get("ai_summary"):
        return _candidate_detail_payload(candidate, latest_upload, [])

    analysis = _build_resume_analysis(candidate, latest_upload)
    _persist_candidate_analysis(candidate_id, analysis)
    _record_admin_audit_log(
        actor or {},
        "resume_analysis_completed",
        "candidate",
        candidate_id,
        {"force": force, "summaryGenerated": bool(analysis.get("ai_summary"))},
    )

    refreshed_candidate = {**candidate, **analysis}
    return _candidate_detail_payload(refreshed_candidate, latest_upload, [])


@router.get("/admin/background-jobs/{job_id}")
def admin_background_job_status(request_obj: Request, job_id: str) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    job = _get_background_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Background job not found")

    return job


@router.get("/admin/audit-logs")
def admin_audit_logs(
    request_obj: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    action: str | None = None,
    entityType: str | None = None,
) -> dict[str, Any]:
    access_token = _get_bearer_token(request_obj)
    user = _get_supabase_user(access_token)
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    query_parts = ["select=*", "order=created_at.desc"]
    if action:
        query_parts.append(f"action=eq.{quote(action)}")
    if entityType:
        query_parts.append(f"entity_type=eq.{quote(entityType)}")

    query_string = "&".join(query_parts)
    logs = _supabase_request(
        f"/rest/v1/admin_audit_logs?{query_string}",
        method="GET",
        bearer_token=settings.supabase_service_role_key,
        use_service_role=True,
    )

    log_rows = logs if isinstance(logs, list) else []
    total = len(log_rows)
    start = (page - 1) * pageSize
    end = start + pageSize
    paginated_logs = log_rows[start:end]

    return {
        "logs": [
            {
                "id": log.get("id"),
                "action": log.get("action"),
                "entityType": log.get("entity_type"),
                "entityId": log.get("entity_id"),
                "actorUserId": log.get("actor_user_id"),
                "actorEmail": log.get("actor_email"),
                "metadata": log.get("metadata") or {},
                "createdAt": log.get("created_at"),
            }
            for log in paginated_logs
        ],
        "pagination": {
            "page": page,
            "pageSize": pageSize,
            "total": total,
            "totalPages": max(1, (total + pageSize - 1) // pageSize),
        },
    }
