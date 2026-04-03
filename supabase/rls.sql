-- Run these statements in the Supabase SQL editor
-- (Dashboard → SQL Editor → New query)

-- ─── detections ───────────────────────────────────────────────────────────────

create table if not exists detections (
  id              bigint generated always as identity primary key,
  detected_at     timestamptz  not null,
  common_name     text         not null,
  scientific_name text         not null,
  confidence      numeric(5,4) not null,
  lat             numeric(9,6),
  lon             numeric(9,6)
);

create index if not exists detections_detected_at_idx on detections (detected_at desc);
create index if not exists detections_species_idx     on detections (common_name);

alter table detections enable row level security;

-- Add is_rare column (safe to re-run)
alter table detections add column if not exists is_rare boolean default false;

do $$ begin
  create policy "Public read" on detections for select using (true);
exception when duplicate_object then null;
end $$;


-- ─── push_subscriptions ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS push_subscriptions (
  id         bigint generated always as identity primary key,
  endpoint   text not null unique,
  p256dh     text not null,
  auth       text not null,
  created_at timestamptz default now()
);

ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;

do $$ begin
  CREATE POLICY "Public insert" ON push_subscriptions FOR INSERT WITH CHECK (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  CREATE POLICY "Public read" ON push_subscriptions FOR SELECT USING (true);
exception when duplicate_object then null;
end $$;


-- ─── species_thresholds (per-species confidence calibration) ──────────────────

create table if not exists species_thresholds (
  common_name    text         primary key,
  min_confidence numeric(5,4) not null default 0.0,
  updated_at     timestamptz  default now()
);

alter table species_thresholds enable row level security;

do $$ begin
  create policy "Public read thresholds" on species_thresholds for select using (true);
exception when duplicate_object then null;
end $$;


-- ─── species_cache (Wikipedia thumbnail cache) ────────────────────────────────

create table if not exists species_cache (
  common_name     text        primary key,
  scientific_name text,
  thumbnail_url   text,
  cached_at       timestamptz default now()
);

alter table species_cache enable row level security;

do $$ begin
  create policy "Public read species_cache" on species_cache for select using (true);
exception when duplicate_object then null;
end $$;
