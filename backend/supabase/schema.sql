-- Supabase schema for JARVIS AI Recruitment Platform
-- Run this in the Supabase SQL editor.

create extension if not exists pgcrypto;

create table if not exists public.candidates (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique,
  full_name text not null,
  role text not null default 'candidate',
  target_role text,
  admin_override_role text,
  current_stage text not null default 'profile_pending',
  ai_summary text,
  ai_score integer,
  ai_skills jsonb not null default '[]'::jsonb,
  ai_experience_level text,
  ai_generated_at timestamptz,
  ai_transcript text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.candidates
  add column if not exists target_role text;

alter table public.candidates
  add column if not exists admin_override_role text;

create table if not exists public.profile_uploads (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  user_id uuid not null,
  file_name text not null,
  file_path text,
  file_url text,
  mime_type text,
  file_size bigint,
  status text not null default 'uploaded',
  created_at timestamptz not null default now()
);

create table if not exists public.interview_slots (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  slot_time timestamptz not null,
  status text not null default 'available',
  created_at timestamptz not null default now()
);

create table if not exists public.interview_sessions (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  application_stage text not null,
  slot_id uuid references public.interview_slots(id) on delete set null,
  status text not null default 'created',
  interview_role text,
  role_source text,
  provider text not null default 'openai-realtime',
  started_at timestamptz,
  ended_at timestamptz,
  duration_seconds integer,
  consent_given boolean not null default false,
  consent_at timestamptz,
  created_at timestamptz not null default now()
);

-- Backward-compatible migration for existing databases where interview_sessions
-- was created before these columns were introduced.
alter table public.interview_sessions
  add column if not exists application_stage text;

alter table public.interview_sessions
  add column if not exists slot_id uuid references public.interview_slots(id) on delete set null;

alter table public.interview_sessions
  add column if not exists interview_role text;

alter table public.interview_sessions
  add column if not exists role_source text;

alter table public.interview_sessions
  add column if not exists provider text;

alter table public.interview_sessions
  add column if not exists started_at timestamptz;

alter table public.interview_sessions
  add column if not exists ended_at timestamptz;

alter table public.interview_sessions
  add column if not exists duration_seconds integer;

alter table public.interview_sessions
  add column if not exists consent_given boolean;

alter table public.interview_sessions
  add column if not exists consent_at timestamptz;

alter table public.interview_sessions
  add column if not exists created_at timestamptz;

update public.interview_sessions
set application_stage = 'profile_pending'
where application_stage is null;

with ranked as (
  select
    id,
    application_stage,
    row_number() over (
      partition by candidate_id, application_stage
      order by created_at desc nulls last, id desc
    ) as rn
  from public.interview_sessions
)
update public.interview_sessions s
set application_stage = ranked.application_stage || '__legacy_' || ranked.rn::text
from ranked
where s.id = ranked.id
  and ranked.rn > 1;

update public.interview_sessions
set provider = 'openai-realtime'
where provider is null;

update public.interview_sessions
set consent_given = false
where consent_given is null;

update public.interview_sessions
set created_at = now()
where created_at is null;

alter table public.interview_sessions
  alter column application_stage set default 'profile_pending';

alter table public.interview_sessions
  alter column application_stage set not null;

alter table public.interview_sessions
  alter column provider set default 'openai-realtime';

alter table public.interview_sessions
  alter column provider set not null;

alter table public.interview_sessions
  alter column consent_given set default false;

alter table public.interview_sessions
  alter column consent_given set not null;

alter table public.interview_sessions
  alter column created_at set default now();

alter table public.interview_sessions
  alter column created_at set not null;

create unique index if not exists idx_interview_sessions_candidate_stage
on public.interview_sessions(candidate_id, application_stage);

create table if not exists public.interview_artifacts (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.interview_sessions(id) on delete cascade,
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  audio_path text,
  audio_url text,
  video_path text,
  video_url text,
  transcript text,
  score_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.interview_artifacts
  add column if not exists hiring_outcome text;

alter table public.interview_artifacts
  add column if not exists outcome_at timestamptz;

alter table public.interview_artifacts
  add column if not exists expires_at timestamptz;

alter table public.interview_artifacts
  add column if not exists archived_at timestamptz;

create index if not exists idx_interview_artifacts_expires_at
on public.interview_artifacts(expires_at);

create table if not exists public.interview_artifact_deletion_log (
  id bigserial primary key,
  artifact_id uuid not null,
  candidate_id uuid,
  deleted_reason text,
  deleted_by uuid,
  deleted_at timestamptz not null default now()
);

insert into storage.buckets (id, name, public)
values ('resumes', 'resumes', true)
on conflict (id) do update
set name = excluded.name,
    public = excluded.public;

insert into storage.buckets (id, name, public)
values ('interview-media', 'interview-media', false)
on conflict (id) do update
set name = excluded.name,
    public = excluded.public;

alter table public.candidates enable row level security;
alter table public.profile_uploads enable row level security;
alter table public.interview_slots enable row level security;
alter table public.interview_sessions enable row level security;
alter table public.interview_artifacts enable row level security;
alter table public.interview_artifact_deletion_log enable row level security;

drop policy if exists "candidate can read own candidate row" on public.candidates;
create policy "candidate can read own candidate row"
on public.candidates
for select
using (auth.uid() = user_id);

drop policy if exists "candidate can insert own candidate row" on public.candidates;
create policy "candidate can insert own candidate row"
on public.candidates
for insert
with check (auth.uid() = user_id);

drop policy if exists "candidate can update own candidate row" on public.candidates;
create policy "candidate can update own candidate row"
on public.candidates
for update
using (auth.uid() = user_id);

drop policy if exists "candidate can read own uploads" on public.profile_uploads;
create policy "candidate can read own uploads"
on public.profile_uploads
for select
using (auth.uid() = user_id);

drop policy if exists "candidate can insert own uploads" on public.profile_uploads;
create policy "candidate can insert own uploads"
on public.profile_uploads
for insert
with check (auth.uid() = user_id);

drop policy if exists "candidate can read own interview slots" on public.interview_slots;
create policy "candidate can read own interview slots"
on public.interview_slots
for select
using (
  exists (
    select 1
    from public.candidates c
    where c.id = interview_slots.candidate_id
      and c.user_id = auth.uid()
  )
);

drop policy if exists "candidate can read own interview sessions" on public.interview_sessions;
create policy "candidate can read own interview sessions"
on public.interview_sessions
for select
using (
  exists (
    select 1
    from public.candidates c
    where c.id = interview_sessions.candidate_id
      and c.user_id = auth.uid()
  )
);

drop policy if exists "candidate can read own interview artifacts" on public.interview_artifacts;
create policy "candidate can read own interview artifacts"
on public.interview_artifacts
for select
using (
  exists (
    select 1
    from public.candidates c
    where c.id = interview_artifacts.candidate_id
      and c.user_id = auth.uid()
  )
);

drop policy if exists "admin can read interview artifact deletion logs" on public.interview_artifact_deletion_log;
create policy "admin can read interview artifact deletion logs"
on public.interview_artifact_deletion_log
for select
using (
  exists (
    select 1
    from public.candidates c
    where c.user_id = auth.uid()
      and c.role = 'admin'
  )
);

drop policy if exists "authenticated users can upload resumes" on storage.objects;
create policy "authenticated users can upload resumes"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'resumes'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "authenticated users can read resumes" on storage.objects;
create policy "authenticated users can read resumes"
on storage.objects
for select
to authenticated
using (bucket_id = 'resumes');

drop policy if exists "authenticated users can update own resumes" on storage.objects;
create policy "authenticated users can update own resumes"
on storage.objects
for update
to authenticated
using (
  bucket_id = 'resumes'
  and split_part(name, '/', 1) = auth.uid()::text
)
with check (
  bucket_id = 'resumes'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "authenticated users can delete own resumes" on storage.objects;
create policy "authenticated users can delete own resumes"
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'resumes'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "authenticated users can upload own interview media" on storage.objects;
create policy "authenticated users can upload own interview media"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'interview-media'
  and split_part(name, '/', 1) = auth.uid()::text
);

drop policy if exists "authenticated users can read own interview media" on storage.objects;
create policy "authenticated users can read own interview media"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'interview-media'
  and split_part(name, '/', 1) = auth.uid()::text
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_candidates_set_updated_at on public.candidates;
create trigger trg_candidates_set_updated_at
before update on public.candidates
for each row
execute function public.set_updated_at();
