-- Run these statements in the Supabase SQL editor
-- (Dashboard → SQL Editor → New query)

-- 1. Create the detections table (skip if already created)
create table if not exists detections (
  id              bigint generated always as identity primary key,
  detected_at     timestamptz  not null,
  common_name     text         not null,
  scientific_name text         not null,
  confidence      numeric(5,4) not null,
  lat             numeric(9,6),
  lon             numeric(9,6)
);

-- Index for time-range queries
create index if not exists detections_detected_at_idx on detections (detected_at desc);

-- 2. Enable Row Level Security
alter table detections enable row level security;

-- 3. Allow anyone (anon key) to read all rows
create policy "Public read"
  on detections
  for select
  using (true);

-- 4. No insert/update/delete for anonymous users.
--    The API backend authenticates with the service role key,
--    which bypasses RLS entirely, so no extra policy is needed for writes.

-- Optional: confirm RLS is active
-- select tablename, rowsecurity from pg_tables where tablename = 'detections';
