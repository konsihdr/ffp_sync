-- FFP Sync: Complete Supabase bootstrap script
-- Safe to run multiple times (idempotent).
--
-- If you want a different storage bucket, replace every occurrence of:
--   ffp-posts

begin;

-- -----------------------------------------------------------------------------
-- 1) Core tables
-- -----------------------------------------------------------------------------

create table if not exists public.ffp_events (
  id bigserial primary key,
  source_uid text,
  summary text not null,
  start text not null,
  "end" text not null,
  is_youth_event boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ffp_posts (
  id bigserial primary key,
  short_code text not null,
  alt text,
  caption text,
  url text,
  display_url text,
  media_url text,
  media_path text,
  media_type text,
  post_date date,
  image_path text,
  video_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Add any missing columns for existing deployments.
alter table public.ffp_events add column if not exists summary text;
alter table public.ffp_events add column if not exists start text;
alter table public.ffp_events add column if not exists "end" text;
alter table public.ffp_events add column if not exists source_uid text;
alter table public.ffp_events add column if not exists is_youth_event boolean not null default false;
alter table public.ffp_events add column if not exists created_at timestamptz not null default now();
alter table public.ffp_events add column if not exists updated_at timestamptz not null default now();

alter table public.ffp_posts add column if not exists short_code text;
alter table public.ffp_posts add column if not exists alt text;
alter table public.ffp_posts add column if not exists caption text;
alter table public.ffp_posts add column if not exists url text;
alter table public.ffp_posts add column if not exists display_url text;
alter table public.ffp_posts add column if not exists media_url text;
alter table public.ffp_posts add column if not exists media_path text;
alter table public.ffp_posts add column if not exists media_type text;
alter table public.ffp_posts add column if not exists post_date date;
alter table public.ffp_posts add column if not exists image_path text;
alter table public.ffp_posts add column if not exists video_path text;
alter table public.ffp_posts add column if not exists created_at timestamptz not null default now();
alter table public.ffp_posts add column if not exists updated_at timestamptz not null default now();

-- -----------------------------------------------------------------------------
-- 2) Constraints + indexes
-- -----------------------------------------------------------------------------

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'ffp_posts_short_code_key'
      and conrelid = 'public.ffp_posts'::regclass
  ) then
    alter table public.ffp_posts
      add constraint ffp_posts_short_code_key unique (short_code);
  end if;
end
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'ffp_posts_media_type_check'
      and conrelid = 'public.ffp_posts'::regclass
  ) then
    alter table public.ffp_posts
      add constraint ffp_posts_media_type_check
      check (media_type is null or media_type in ('image', 'video'));
  end if;
end
$$;

create index if not exists idx_ffp_events_start on public.ffp_events (start);
create index if not exists idx_ffp_events_is_youth_event on public.ffp_events (is_youth_event);
create unique index if not exists idx_ffp_events_source_uid_unique
on public.ffp_events (source_uid)
where source_uid is not null;
create index if not exists idx_ffp_posts_post_date on public.ffp_posts (post_date);
create index if not exists idx_ffp_posts_media_type on public.ffp_posts (media_type);

-- -----------------------------------------------------------------------------
-- 3) updated_at maintenance trigger
-- -----------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
begin
  if not exists (
    select 1 from pg_trigger
    where tgname = 'trg_ffp_events_set_updated_at'
  ) then
    create trigger trg_ffp_events_set_updated_at
      before update on public.ffp_events
      for each row
      execute function public.set_updated_at();
  end if;

  if not exists (
    select 1 from pg_trigger
    where tgname = 'trg_ffp_posts_set_updated_at'
  ) then
    create trigger trg_ffp_posts_set_updated_at
      before update on public.ffp_posts
      for each row
      execute function public.set_updated_at();
  end if;
end
$$;

-- -----------------------------------------------------------------------------
-- 4) Backfill + canonical media fields
-- -----------------------------------------------------------------------------

update public.ffp_posts
set media_path = coalesce(media_path, video_path, image_path)
where media_path is null;

update public.ffp_posts
set media_type = case
  when media_type is not null then media_type
  when video_path is not null then 'video'
  when image_path is not null then 'image'
  else null
end
where media_type is null;

update public.ffp_posts
set media_url = coalesce(media_url, display_url, url)
where media_url is null;

update public.ffp_posts
set display_url = coalesce(display_url, media_url, url)
where display_url is null;

-- -----------------------------------------------------------------------------
-- 5) RLS + table policies (public read, service-role writes)
-- -----------------------------------------------------------------------------

alter table public.ffp_events enable row level security;
alter table public.ffp_posts enable row level security;

-- Public read for consumer apps.
do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'ffp_events'
      and policyname = 'ffp_events_public_read'
  ) then
    create policy ffp_events_public_read
      on public.ffp_events
      for select
      to anon, authenticated
      using (true);
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'ffp_posts'
      and policyname = 'ffp_posts_public_read'
  ) then
    create policy ffp_posts_public_read
      on public.ffp_posts
      for select
      to anon, authenticated
      using (true);
  end if;
end
$$;

-- Grants for read-only client access (consumer apps).
grant usage on schema public to anon, authenticated;
grant select on public.ffp_events to anon, authenticated;
grant select on public.ffp_posts to anon, authenticated;

-- Grants for service_role (sync service writes via Data API / PostgREST).
-- Required from May 30 2026: new projects no longer auto-expose public tables.
grant usage on schema public to service_role;
grant select, insert, update, delete on public.ffp_events to service_role;
grant select, insert, update, delete on public.ffp_posts to service_role;
grant usage, select on all sequences in schema public to service_role;

-- -----------------------------------------------------------------------------
-- 6) Storage bucket + storage policies
-- -----------------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('ffp-posts', 'ffp-posts', true)
on conflict (id) do update
set public = excluded.public;

-- Remove broad SELECT policy to prevent bucket-wide file listing by clients.
do $$
begin
  if exists (
    select 1 from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname = 'ffp_posts_storage_public_read'
  ) then
    drop policy ffp_posts_storage_public_read on storage.objects;
  end if;

  -- Optional: allow authenticated users to manage files in this bucket.
  -- Service-role key bypasses RLS anyway; this is mainly for dashboard/user workflows.
  if not exists (
    select 1 from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname = 'ffp_posts_storage_auth_insert'
  ) then
    create policy ffp_posts_storage_auth_insert
      on storage.objects
      for insert
      to authenticated
      with check (bucket_id = 'ffp-posts');
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname = 'ffp_posts_storage_auth_update'
  ) then
    create policy ffp_posts_storage_auth_update
      on storage.objects
      for update
      to authenticated
      using (bucket_id = 'ffp-posts')
      with check (bucket_id = 'ffp-posts');
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname = 'ffp_posts_storage_auth_delete'
  ) then
    create policy ffp_posts_storage_auth_delete
      on storage.objects
      for delete
      to authenticated
      using (bucket_id = 'ffp-posts');
  end if;
end
$$;

commit;
