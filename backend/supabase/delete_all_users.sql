-- DANGEROUS: This permanently deletes all users and related app data.
-- Run only if you want to reset the project completely.

begin;

delete from storage.objects
where bucket_id = 'resumes';

delete from public.profile_uploads;
delete from public.interview_slots;
delete from public.candidates;

delete from auth.users;

commit;
