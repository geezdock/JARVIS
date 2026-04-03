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

### Phase 8: Video Interview Recording [55% - IN PROGRESS]

**Goal:** Enable candidates to record video interviews during scheduled slots.

#### 8.1 Choose Video Solution
- [ ] Evaluate: Twilio Video, Daily.co, Whereby, or browser WebRTC with recording
- [ ] Decide: Live vs recorded, moderation requirements

#### 8.2 Create Interview Recording Page
- [ ] Create new component [frontend/src/pages/candidate/Interview.jsx](frontend/src/pages/candidate/Interview.jsx)
- [ ] Implement:
  - Camera/microphone permission request
  - Recording UI with start/stop buttons
  - Video preview during recording
  - Upload to Storage after recording
- [ ] Add route to candidate router pointing to this page

#### 8.3 Build Backend Interview Endpoint
- [ ] Create `POST /candidate/interview-upload` endpoint to:
  - Accept video file and interview metadata
  - Validate interview slot timing
  - Store video file in Storage bucket
  - Update interview_slots.status to "completed"
  - Trigger transcription/analysis if needed

#### 8.4 Admin Interview Playback
- [ ] Update [frontend/src/pages/admin/CandidateDetails.jsx](frontend/src/pages/admin/CandidateDetails.jsx) to:
  - Display video player for completed interviews
  - Show transcription/summary if available

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
- [ ] Wire full OpenAI Realtime media stream in browser (current room uses role-based scripted AI voice prompts and browser capture)
- [ ] Add admin playback UI for saved interview artifacts
- [ ] Finalize session scoring rubric and transcript enrichment

---

### Phase 9: Search, Filter & Admin Features [0% - NOT STARTED]

#### 9.1 Candidate Search & Filtering
- [ ] Add search bar to [frontend/src/pages/admin/Dashboard.jsx](frontend/src/pages/admin/Dashboard.jsx)
- [ ] Implement filters: stage, score range, upload status
- [ ] Optimize `GET /admin/candidates` to accept query params: `?search=`, `?stage=`, `?minScore=`

#### 9.2 Candidate Stage Management
- [ ] Create endpoint `PATCH /admin/candidates/{candidate_id}` to update `current_stage`
- [ ] Stages: `profile_pending` → `under_review` → `interview_scheduled` → `interview_completed` → `offer_extended` / `rejected`
- [ ] Add stage transition UI in CandidateDetails page

#### 9.3 Bulk Operations
- [ ] Allow admins to multi-select candidates and bulk update stage or send emails

**Dependencies:** All previous phases

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

### Phase 11: Testing [0% - NOT STARTED]

#### 11.1 Backend Tests
- [ ] Unit tests for Supabase request helpers
- [ ] API endpoint tests for auth, candidates, uploads
- [ ] Admin authorization tests
- [ ] Error handling tests

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
| **AI Summarization** | ✅ Complete | OpenAI-backed analysis with heuristic fallback |
| **Interview Role Resolution** | ✅ Complete | Dedicated fields + fallback role routing |
| **Video Interviewing** | ❌ Not Started | No recording capability yet |
| **Search & Filters** | ❌ Not Started | Basic list view only |
| **Email Notifications** | ❌ Not Started | No email integration |
| **Testing** | ❌ Not Started | No test suite |
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

---

## 📋 Notes

- All backend routes include proper error handling and token validation
- Automatic candidate record creation prevents orphaned data
- Admin routes check `_is_admin()` before returning data
- Frontend auto-detects admin role from email (contains "admin") or user_metadata.role
- CORS is configured for frontend origin in [backend/app/main.py](backend/app/main.py)
- Session bootstrap ensures user is logged in before rendering protected pages
