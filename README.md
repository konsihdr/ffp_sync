# FFP Sync — Supabase Edge Functions

Sync service for Freiwillige Feuerwehr Pöttmes (FFP).  
Writes Google Calendar events and Instagram posts (+ media) into Supabase (Postgres + Storage) via two Deno edge functions scheduled with pg_cron.

---

## What it syncs

| Source | Destination |
|--------|-------------|
| Google Calendar ICS | `ffp_events` table |
| Instagram via Apify | `ffp_posts` table + Storage bucket (`ffp-posts`) |

---

## Edge Functions

| Function | Schedule | What it does |
|----------|----------|--------------|
| `sync-calendar` | every night | Fetch ICS → upsert `ffp_events` |
| `sync-posts` | every 2 h | Call Apify → upload media → upsert `ffp_posts` |

---

## Deploy

```bash
supabase login
supabase link --project-ref <project-ref>

supabase secrets set \
  CALENDAR_URL="<google-calendar-ics-url>" \
  APIFY_TOKEN="<token>" \
  SUPABASE_SERVICE_ROLE_KEY="<key>" \
  SUPABASE_STORAGE_BUCKET="ffp-posts"

supabase functions deploy sync-calendar
supabase functions deploy sync-posts
```

## Trigger manually

```bash
curl -X POST https://<project-ref>.functions.supabase.co/sync-calendar \
  -H "Authorization: Bearer <service-role-key>"

curl -X POST https://<project-ref>.functions.supabase.co/sync-posts \
  -H "Authorization: Bearer <service-role-key>"
```

---

## Setup

| File | Purpose |
|------|---------|
| `setup/supabase_setup.sql` | Full schema bootstrap (idempotent) — run once |
| `setup/schedule_edge_functions.sql` | pg_cron job definitions |
| `setup/SUPABASE_SETUP.md` | Step-by-step setup guide |
