# Supabase Setup Instructions

## 0. Run the Complete SQL Setup Script

For a fresh Supabase project, run:

1. Open Supabase Studio -> `SQL Editor`
2. Open and execute [`supabase_setup.sql`](./supabase_setup.sql)
3. Verify that tables `ffp_events`, `ffp_posts` and bucket `ffp-posts` were created

The script is idempotent (safe to run multiple times).

## 1. Required Environment Variables

```bash
export SUPABASE_URL="https://<project-ref>.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<service-role-key>"
export SUPABASE_STORAGE_BUCKET="ffp-posts"
export APIFY_TOKEN="<apify-token>"
```

Use the **service role key** for this sync job (server-side only, never in clients).

## 2. Manual SQL (Reference)

This section mirrors the important schema created by `supabase_setup.sql`.
Use this only as reference if you need to customize setup manually.

```sql
create table if not exists public.ffp_events (
  id bigserial primary key,
  source_uid text,
  summary text not null,
  start text not null,
  "end" text not null,
  is_youth_event boolean default false
);

create table if not exists public.ffp_posts (
  id bigserial primary key,
  short_code text not null unique,
  alt text,
  caption text,
  url text,
  display_url text,
  media_url text,
  media_path text,
  media_type text,
  post_date date,
  image_path text,
  video_path text
);
```

If your table already exists, apply this migration:

```sql
alter table public.ffp_events add column if not exists source_uid text;
create unique index if not exists idx_ffp_events_source_uid_unique
on public.ffp_events (source_uid)
where source_uid is not null;

alter table public.ffp_posts add column if not exists media_url text;
alter table public.ffp_posts add column if not exists media_path text;
alter table public.ffp_posts add column if not exists media_type text;
```

## 3. Create Storage Bucket

`supabase_setup.sql` already creates the `ffp-posts` bucket (public).
If you use a different bucket name, update the SQL script and `SUPABASE_STORAGE_BUCKET`.

For simple public serving, keep the bucket public.

To avoid bucket file-listing warnings, do not keep a broad `SELECT` policy on `storage.objects`.
If you already have one, run:

```sql
drop policy if exists ffp_posts_storage_public_read on storage.objects;
```

## 4. RLS Guidance

For this sync job, easiest setup is:
- Keep RLS enabled
- Add policies that allow service role operations (service role bypasses RLS automatically)

For consumer apps, add read policies as needed.

## 5. Verify Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run sync:
   ```bash
   python3 sync_script.py
   ```
3. Verify rows in `ffp_events` and `ffp_posts`
4. Verify uploaded files in Storage bucket

## 6. Migrate Existing PocketBase Data (One-time)

Set migration env vars:

```bash
export POCKETBASE_URL="https://your-pocketbase.example.com"
export POCKETBASE_EMAIL="your-pocketbase-user@example.com"
export POCKETBASE_PASSWORD="your-pocketbase-password"
```

Preview first:

```bash
python3 migrations/migrate_pocketbase_to_supabase.py --dry-run
```

Run migration:

```bash
python3 migrations/migrate_pocketbase_to_supabase.py
```

Useful flags:
- `--events-only`
- `--posts-only`
- `--no-media-copy`

## 7. Migration Notes from PocketBase

- Field names in Supabase use snake_case (`short_code`, `display_url`, `post_date`).
- Events are keyed by stable ICS `source_uid` to avoid unnecessary mass updates.
- The sync writes one canonical file link in `display_url` for both images and videos.
- Optional unified fields: `media_url`, `media_path`, `media_type`.
- Legacy `image_path` and `video_path` are still supported.
- Duplicate detection for posts is based on unique `short_code`.
