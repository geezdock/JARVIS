# JARVIS Project To-Do

## Project Status

### ✅ COMPLETED PHASES

#### Phase 1: Core Infrastructure (DONE)
- ✅ Supabase schema created with three tables: `candidates`, `profile_uploads`, `interview_slots`
- ✅ Row-level security (RLS) policies configured for all tables
- ✅ Supabase auth integration with email/password signup
- ✅ Role derivation system (admin/candidate detection via user metadata and email)

#### Phase 2: Backend API (DONE)
All endpoints built and Supabase-integrated:
- ✅ `GET /health` - Service health check
- ✅ `GET /candidate/dashboard` - Candidate stats (profile, resume, interview status)
- ✅ `GET /candidate/interview-slots` - List booked interview slots
- ✅ `POST /candidate/interview-slots` - Book new interview slot
- ✅ `POST /candidate/profile-upload` - Upload profile with metadata persistence
- ✅ `GET /admin/candidates` - List all candidates with scores
- ✅ `GET /admin/candidates/{candidate_id}` - Candidate detail with transcript and summary

#### Phase 3: Frontend Auth & Pages (DONE)
- ✅ Supabase auth context with session management
- ✅ Login page with email/password authentication
- ✅ Signup page with first name, last name, and auth role selection
- ✅ Landing page with navigation
- ✅ Candidate Dashboard page showing stats, resume state, and resolved interview role
- ✅ Profile Upload page with target interview role text input and PDF upload
- ✅ Interview page with start action and role-specific interview flow/questions
- ✅ Admin Dashboard page with candidate grid
- ✅ Admin Candidate Details page with resume info, AI summary, and interview role controls
- ✅ Role-based route protection (authenticated and role-specific guards)

#### Phase 4: UI Components & Styling (DONE)
- ✅ Tailwind CSS configured and working
- ✅ Reusable UI components: Button, Card, Input
- ✅ Navbar with navigation and logout
- ✅ Responsive layout
- ✅ Toast notifications and form validation

#### Phase 5: API Integration (DONE)
- ✅ Axios configured with Supabase token forwarding
- ✅ Backend token validation using Supabase auth endpoint
- ✅ Bearer token extraction from request headers
- ✅ Service role key for admin operations
- ✅ Automatic candidate record creation on first login

#### Phase 6: File Storage & Upload Handling (DONE)
- ✅ Supabase Storage bucket created (`resumes` + `interview-media`)
- ✅ Frontend upload-to-storage flow with progress tracking
- ✅ Backend metadata persistence for file URLs
- ✅ Signed URL generation for secure access

#### Phase 7: AI Resume Summarization (DONE)
- ✅ OpenAI integration for resume analysis
- ✅ AI-powered scoring and skill extraction
- ✅ Dynamic summary display in admin dashboard

#### Phase 7.5: Role-Aware Interview Routing (DONE)
- ✅ Dedicated interview role fields (`target_role`, `admin_override_role`)
- ✅ Role-specific interview plans and questions
- ✅ Fallback resolution order with flexibility

#### Phase 8: Video Interview Recording (DONE)
- ✅ Browser-based WebRTC recording
- ✅ Interview session management with consent gates
- ✅ Private media storage with signed access
- ✅ Admin playback UI with video player
- ✅ Transcript autosave with versioning

#### Phase 8.5: AI-Powered Scoring System (DONE)
- ✅ Three-part weighted scoring model (30/60/10)
- ✅ Strict LLM-based evaluation (no heuristic fallbacks)
- ✅ OpenAI reliability layer (retry + backoff + queue)
- ✅ Scoring retry endpoints (candidate + admin)
- ✅ Admin UI status badges and manual retry buttons
- ✅ Graceful handling of service unavailability

---

## 🚀 NEXT PRIORITIES (Ordered by Sequence)

### Phase 6: File Storage & Upload Handling [100% - DONE]

**Goal:** Enable actual file uploads to Supabase Storage and serve resumés from files.

**Current state:** Frontend upload-to-storage flow is wired, backend metadata persistence accepts storage paths/URLs, and `backend/supabase/schema.sql` provisions the `resumes` bucket plus storage policies.

#### 6.1 Create Supabase Storage Bucket
- [x] Create a public bucket named `resumes` in Supabase Storage
- [x] Configure CORS policy to allow frontend uploads
- [x] Document bucket path conventions

#### 6.2 Implement File Upload to Storage
- [x] Update `POST /candidate/profile-upload` to persist `file_path` and `file_url`
- [x] Update [frontend/src/pages/candidate/ProfileUpload.jsx](frontend/src/pages/candidate/ProfileUpload.jsx) to upload the PDF directly to Supabase Storage
- [x] Store `file_url` from storage in database after successful upload
- [x] Display upload progress indicator

#### 6.3 Test File Upload Flow
- [x] Upload a PDF from frontend
- [x] Verify file appears in Storage bucket
- [x] Verify database record has valid `file_url`
- [x] Test file download/preview from admin dashboard

**Dependencies:** Phase 5 (API Integration) must be complete

---

### Phase 7: AI Resume Summarization [100% - DONE]

**Goal:** Analyze uploaded resumés and generate AI-powered summaries and scoring.

#### 7.1 Choose AI Provider
- [x] Evaluate: OpenAI GPT-4, Claude, or similar
- [x] Add API key to [backend/.env.example](backend/.env.example)
- [x] Document API costs and rate limits

#### 7.2 Build Resume Analysis Endpoint
- [x] Create new endpoint `POST /admin/analyze-resume/{candidate_id}` to generate resume analysis on demand
- [x] Implement:
  - PDF text extraction from uploaded resume URL
  - Resume summarization and scoring heuristics
  - Structured response: summary, key skills, experience level, score
- [x] Update database schema to add `ai_summary`, `ai_score`, `ai_skills`, `ai_experience_level`, `ai_generated_at` fields to `candidates` table

#### 7.2 Integrate Summary Display
- [x] Update [frontend/src/pages/admin/CandidateDetails.jsx](frontend/src/pages/admin/CandidateDetails.jsx) to:
  - Display dynamic AI summary from database
  - Show extracted skills and qualifications
  - Display AI-generated score
  
#### 7.3 Test Analysis Pipeline
- [x] Upload sample resume
- [x] Trigger AI analysis
- [x] Verify results display properly

**Dependencies:** Phase 6 (File Storage) is complete

---

### Phase 7.5: Role-Aware Interview Routing [100% - DONE]

**Goal:** Ensure interview context and AI analysis are driven by the actual interview role, not auth role.

- [x] Add dedicated fields in `candidates`: `target_role`, `admin_override_role`
- [x] Keep auth role (`candidate`/`admin`) separate from interview role
- [x] Add candidate target role text input in [frontend/src/pages/candidate/ProfileUpload.jsx](frontend/src/pages/candidate/ProfileUpload.jsx)
- [x] Persist candidate target role through `POST /candidate/profile-upload`
- [x] Add admin override controls in [frontend/src/pages/admin/CandidateDetails.jsx](frontend/src/pages/admin/CandidateDetails.jsx)
- [x] Add `PATCH /admin/candidates/{candidate_id}/interview-role`
- [x] Implement role fallback order:
  - admin override role
  - candidate target role
  - inferred role from resume text
- [x] Use resolved interview role in AI prompt and summaries
- [x] Generate role-specific interview plans/questions in interview APIs
- [x] Show resolved interview role and role source in candidate/admin dashboards

**Dependencies:** Phase 7 (AI Resume Summarization) is complete

---

### Phase 8: Video Interview Recording [100% - DONE]

**Goal:** Enable candidates to record video interviews during scheduled slots.

#### 8.1 Choose Video Solution
- [x] Evaluate: Twilio Video, Daily.co, Whereby, or browser WebRTC with recording
- [x] Decide: live browser-based interview room with consent-gated capture and private storage

#### 8.2 Create Interview Recording Page
- [x] Create new component [frontend/src/pages/candidate/Interview.jsx](frontend/src/pages/candidate/Interview.jsx)
- [ ] Implement:
  - [x] Camera/microphone permission request
  - [x] Recording UI with start/stop buttons
  - [x] Video preview during recording
  - [x] Upload to Storage after recording
- [x] Add route to candidate router pointing to this page

#### 8.3 Build Backend Interview Endpoint
- [x] Create interview session endpoints to:
  - [x] Accept interview metadata and consent state
  - [x] Validate interview session ownership and application stage
  - [x] Store media in private Storage bucket via signed upload URLs
  - [x] Update `interview_sessions.status` and `interview_slots.status`
  - [x] Persist transcript / score payload for later analysis

#### 8.4 Admin Interview Playback
- [x] Update [frontend/src/pages/admin/CandidateDetails.jsx](frontend/src/pages/admin/CandidateDetails.jsx) to:
  - [x] Display video player for completed interviews
  - [x] Show transcription/summary if available
- [x] Video player renders with controls from signed interview URLs
- [x] Transcript display integrated with interview timeline

**Dependencies:** Phase 6 (File Storage), Phase 7 (AI Analysis optional)

**Current progress update:**
- [x] Candidate interview room page scaffold created at [frontend/src/pages/candidate/Interview.jsx](frontend/src/pages/candidate/Interview.jsx)
- [x] Camera/microphone permission + local media preview implemented
- [x] Start Interview routes directly to the live interview room (`/interview/live`)
- [x] Consent notice is shown before any session creation or media permission request
- [x] Backend session endpoints added:
  - `POST /candidate/interview-session/start`
  - `POST /candidate/interview-session/{session_id}/complete`
  - `POST /candidate/storage/signed-interview-upload`
  - `GET /admin/interview-session/{session_id}`
- [x] Interview session schema added (`interview_sessions`, `interview_artifacts`) and `interview-media` bucket policies
- [x] Session creation is consent-gated and limited to one session per application stage
- [x] Interview media is stored privately with signed upload/read access
- [x] Session resume is verified against the backend before reusing interview context
- [x] Admin access checks use trusted Supabase metadata only
- [x] Signed interview upload nonces are validated and consumed through shared storage, not process memory
- [x] Expired artifacts can be recorded and cleaned up with audit logging
- [x] Strict interview focus lock is enforced across app routes with termination on fullscreen exit/tab leave/route leave
- [x] Incremental transcript autosave includes versioning to prevent stale out-of-order writes
- [x] AI interviewer output mode is configurable (`INTERVIEW_AI_OUTPUT_MODE`) with browser TTS fallback visibility in the candidate room
- [x] Wire OpenAI Realtime browser transport with authenticated session token endpoint, WebRTC audio channel, realtime transcript ingestion, and browser TTS fallback
- [x] Add admin playback UI for saved interview artifacts
- [x] Finalize session scoring rubric and transcript enrichment
- [x] Add admin mini timeline per interview session (started, ended, termination reason, rubric delta)

---

### Phase 8.5: AI-Powered Scoring System [100% - DONE]

**Goal:** Implement strict LLM-based evaluation for all interview components with reliability guarantees.

#### 8.5.1 Three-Part Scoring Model
- [x] Resume Scoring (30% weight):
  - [x] LLM evaluates 5 categories (skills_match, experience, projects, education, quality) on 0-10 scale
  - [x] Normalized formula: `resume_score = (skills*1.0 + exp*0.8 + proj*0.6 + edu*0.3 + quality*0.3) * 3`
  - [x] Final range: 0-100
- [x] Interview Scoring (60% weight):
  - [x] LLM evaluates each Q&A pair on 5 dimensions: technical, problem_solving, communication, confidence, relevance
  - [x] Normalized formula: `interview_score = (tech*2.0 + problem*1.5 + comm*1.0 + confidence*1.0 + relevance*0.5) * 3`
  - [x] Final range: 0-100
- [x] Behavioral Scoring (10% weight):
  - [x] LLM assesses filler words, pauses, hesitation patterns
  - [x] Direct 0-10 scale
  - [x] Clamped 0-10
- [x] Final Score Calculation:
  - [x] Formula: `overall = (resume_score * 0.3) + (interview_score * 0.6) + (behavior_score)`
  - [x] Clamped 0-100

#### 8.5.2 Strict LLM Migration
- [x] Eliminate heuristic-based scoring fallbacks
- [x] Replace `_build_interview_scoring_rubric()` to call OpenAI API exclusively
- [x] Implement `_openai_interview_analysis()` for per-answer structured evaluation
- [x] Implement `_openai_resume_analysis()` for structured JSON LLM responses
- [x] Remove all keyword matching, length-based heuristics
- [x] Backend is authoritative for all scoring (removed client-side score calculations)

#### 8.5.3 OpenAI Reliability Layer
- [x] Implement `_openai_chat_completion_with_retry()` shared helper:
  - [x] Exponential backoff: 0.8s → 1.6s → 3.2s
  - [x] Retry on transient failures: 408, 429, 5xx
  - [x] Max 3 attempts
- [x] Add `_ensure_openai_scoring_ready()` preflight check:
  - [x] Validates OpenAI availability at session start (30s timeout)
  - [x] Prevents bad UX if service is down
- [x] Implement scoring completion queue:
  - [x] On scoring failure, mark `scoringStatus: pending` (not hard failure)
  - [x] Store error context in `scoringError` field
  - [x] Complete interview session with transcript saved
  - [x] Allow manual retry on demand

#### 8.5.4 Retry Endpoints
- [x] `POST /candidate/interview-session/{session_id}/score/retry`:
  - [x] Candidate self-serve retry for pending scores
  - [x] Validates session ownership
  - [x] Updates scoring status on success
- [x] `POST /admin/interview-session/{session_id}/score/retry`:
  - [x] Admin-only force retry for stuck/pending scores
  - [x] Validates admin role
  - [x] Re-runs entire scoring pipeline

#### 8.5.5 Admin UI for Scoring Status
- [x] Status pills in timeline:
  - [x] Green "Scored" for completed evaluations
  - [x] Amber "Scoring Pending" for failed/queued scores
- [x] Scoring rubric panel enhancements:
  - [x] Status pill display
  - [x] Conditional retry button (shown only if pending)
  - [x] Error message display with automatic fade
  - [x] Component breakdown visualization
  - [x] LLM behavior notes display
- [x] Admin list filtering:
  - [x] Ignores pending scores when ranking/sorting
  - [x] Falls back to resume score if interview pending

#### 8.5.6 Testing & Validation
- [x] Backend syntax validation (compile checks)
- [x] Frontend build validation (no type errors)
- [x] Health check confirmation
- [x] End-to-end scoring pipeline tested

**Dependencies:** Phase 7.5 (Role-Aware Routing)

**Current Implementation Status:**
- All scoring endpoints fully wired and tested
- Retry logic handles OpenAI transient failures gracefully
- Admin dashboard provides full visibility into scoring state
- No hard failures on service unavailability; user can manually retry

---

### Phase 9: Search, Filter & Admin Features [92% - IN PROGRESS]

**Goal:** Add advanced admin capabilities for candidate management and filtering.

#### 9.1 Candidate Search & Filtering
- [x] Add search bar to [frontend/src/pages/admin/Dashboard.jsx](frontend/src/pages/admin/Dashboard.jsx)
- [x] Implement filters: stage + sort by score
- [x] Optimize `GET /admin/candidates` to accept query params: `?search=` and `?stage=`
- [x] Backend filtering applied server-side for efficiency
- [x] Clear filters button for easy reset

#### 9.2 Candidate Stage Management
- [x] Database schema already includes `current_stage` field with valid stages
- [x] Create endpoint `PATCH /admin/candidates/{candidate_id}/stage` to update stage
- [x] Validate stage values: profile_pending, under_review, interview_scheduled, interview_completed, offer_extended, rejected
- [x] Add stage transition UI in [frontend/src/pages/admin/CandidateDetails.jsx](frontend/src/pages/admin/CandidateDetails.jsx)
- [x] Display pipeline stages and current stage selection
- [x] Real-time stage updates with toast notifications

#### 9.3 Bulk Operations [75% - IN PROGRESS]
- [x] Allow admins to multi-select candidates and bulk update stage
- [ ] Bulk operations for sending emails (requires Phase 10)
- [ ] Progress indicator for bulk operations

**Dependencies:** Phase 7.5 (Role-Aware Routing)

**Current Implementation Status:**
- ✅ Server-side filtering on backend (search, stage)
- ✅ Enhanced admin dashboard with advanced filter controls
- ✅ Inline score sorting dropdown (high-to-low / low-to-high)
- ✅ Stage transition UI in candidate details page
- ✅ Multi-select bulk stage updates from the admin list
- ✅ All backend/frontend code validated (no syntax/type errors)
- ✅ Frontend builds successfully

**Testing Status:**
- Backend compiles: ✓
- Frontend builds: ✓ (2241 modules)
- No type/syntax errors: ✓

---

### Phase 10: Email & Notifications [0% - NOT STARTED]

**Goal:** Keep candidates informed of status changes.

#### 10.1 Email Setup
- [ ] Choose provider: SendGrid, Mailgun, AWS SES, or Supabase built-in emails
- [ ] Add service credentials to [backend/.env.example](backend/.env.example)
- [ ] Create email template service in backend

#### 10.2 Email Triggers
- [ ] Send welcome email on signup
- [ ] Send notification when interview slot is scheduled
- [ ] Send notification when stage changes (e.g., "Your application has been reviewed")
- [ ] Send rejection/offer email when applicable

#### 10.3 Toast & In-App Notifications
- [ ] Add real-time notifications to frontend (already has toast component)
- [ ] Emit socket events or polling for live updates

**Dependencies:** All previous phases

---

### Phase 11: Testing [35% - IN PROGRESS]

#### 11.1 Backend Tests
- [ ] Unit tests for Supabase request helpers
- [x] API endpoint tests for core admin + health flows (pytest)
- [x] Admin authorization behavior covered in route-level tests
- [x] Error-path assertions for selected endpoints

#### 11.2 Frontend Tests
- [ ] Auth flow tests
- [ ] Component rendering tests
- [ ] API integration tests
- [ ] Form validation tests

**Dependencies:** All functionality complete (Phases 6-10)

---

### Phase 12: Documentation & Deployment [0% - NOT STARTED]

#### 12.1 Documentation
- [ ] API documentation (endpoints, request/response shapes)
- [ ] Setup guide for developers and deployment
- [ ] Update [README.md](README.md) with full features
- [ ] Create CONTRIBUTING.md for future builders

#### 12.2 Docker Setup
- [ ] Create Dockerfile for backend
- [ ] Create Dockerfile for frontend (build image)
- [ ] Create docker-compose.yml for local development

#### 12.3 Deployment
- [ ] Prepare backend for cloud hosting (Heroku, Railway, Render, AWS)
- [ ] Deploy frontend to Vercel or similar
- [ ] Configure production environment variables
- [ ] Set up CI/CD pipeline (GitHub Actions)

#### 12.4 Performance & Security
- [ ] Add rate limiting to backend
- [ ] Implement request validation and sanitization
- [ ] Add monitoring and error tracking (Sentry)
- [ ] Optimize frontend bundle size
- [ ] Enable caching strategies

**Dependencies:** All features complete, comprehensive testing done

---

### Platform Improvements [100% - DONE]
- ✅ Backend pytest suite added for health, admin filtering, stage changes, audit logs, and background jobs
- ✅ Admin candidate pagination added to the dashboard UI
- ✅ Background job queue added for heavy admin operations
- ✅ Audit logs added for key admin actions and exposed through a paginated endpoint
- ✅ Route-level bundle splitting added with React.lazy and Suspense

---

## 🎯 Quick Reference: What Works Now

| Feature | Status | Notes |
|---------|--------|-------|
| User Auth (Signup/Login) | ✅ Complete | Email/password with Supabase |
| Candidate Dashboard | ✅ Complete | Shows stats and resolved interview role |
| Profile Upload Form | ✅ Complete | PDF upload + target interview role text input |
| Interview Flow | ✅ Complete | Start interview + role-specific plan/questions |
| Admin Candidate List | ✅ Complete | Shows all candidates with basic scores |
| Admin Candidate Details | ✅ Complete | AI summary + editable target/override role |
| Backend API Architecture | ✅ Complete | All endpoints structured and ready |
| Supabase Integration | ✅ Complete | Auth, RLS, database all configured |
| UI Components | ✅ Complete | Tailwind, responsive, accessible |
| **File Storage** | ✅ Complete | Resume uploads stored in Supabase Storage |
| **AI Summarization** | ✅ Complete | OpenAI-backed analysis with strict LLM scoring flow |
| **Interview Role Resolution** | ✅ Complete | Dedicated fields + fallback role routing |
| **Video Interviewing** | ✅ Complete | Recording, playback, transcript capture all working |
| **Interview Scoring** | ✅ Complete | Strict LLM-based three-part model with reliability layer |
| **Scoring Retry/Queue** | ✅ Complete | Handles OpenAI failures gracefully, manual retry available |
| **Admin Scoring UI** | ✅ Complete | Status pills, retry buttons, error messages in dashboard |
| **Search & Filters** | ✅ Complete | Advanced search, stage filter, score sort on dashboard |
| **Stage Management** | ✅ Complete | Update candidate stage with validation and pipeline display |
| **Bulk Operations** | ✅ In Progress | Multi-select bulk stage updates complete; email bulk ops deferred |
| **Audit Logs** | ✅ Complete | Admin actions are recorded and queryable |
| **Background Jobs** | ✅ Complete | Resume analysis and artifact cleanup can run asynchronously |
| **Bundle Splitting** | ✅ Complete | Route-level lazy loading reduces the main frontend bundle |
| **Email Notifications** | ❌ Not Started | No email integration |
| **Testing** | ✅ In Progress | Backend pytest suite added; frontend tests pending |
| **Deployment** | ❌ Not Started | Development setup only |

---

## 🔄 Development Workflow

### Start Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env with Supabase credentials
python -m uvicorn app.main:app --reload --port 8000
```

### Start Frontend
```powershell
cd frontend
npm install
npm run dev
```

### Apply Schema (if not done)
1. Go to Supabase project dashboard
2. Open SQL Editor
3. Paste contents of [backend/supabase/schema.sql](backend/supabase/schema.sql)
4. Run all queries

### Run Backend Tests
```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

---

## 📋 Notes

- All backend routes include proper error handling and token validation
- Automatic candidate record creation prevents orphaned data
- Admin routes check `_is_admin()` before returning data
- Frontend routes candidates to the interview room after session bootstrap; admin access is enforced server-side through trusted metadata
- CORS is configured for frontend origin in [backend/app/main.py](backend/app/main.py)
- Session bootstrap ensures user is logged in before rendering protected pages
- Current bulk-stage API supports POST and PATCH for compatibility; frontend uses POST
- Remaining near-term gap in admin workflow is bulk-operation progress visibility and email actions (Phase 10)
