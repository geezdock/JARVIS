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

insert into storage.buckets (id, name, public)
values ('resumes', 'resumes', true)
on conflict (id) do update
set name = excluded.name,
    public = excluded.public;

alter table public.candidates enable row level security;
alter table public.profile_uploads enable row level security;
alter table public.interview_slots enable row level security;

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
