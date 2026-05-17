
alter database postgres set app.supabase_functions_url = 'https://<PROJECT_REF>.functions.supabase.co';
alter database postgres set app.supabase_service_role_key = '<SERVICE_ROLE_KEY>';

-- Enable extensions (idempotent)
create extension if not exists pg_net   schema extensions;
create extension if not exists pg_cron  schema cron;

-- Remove old schedules if they exist
select cron.unschedule('sync-calendar') where exists (
  select 1 from cron.job where jobname = 'sync-calendar'
);
select cron.unschedule('sync-posts') where exists (
  select 1 from cron.job where jobname = 'sync-posts'
);

-- Sync calendar every 6 hours
select cron.schedule(
  'sync-calendar',
  '0 */6 * * *',
  $$
  select net.http_post(
    url := current_setting('app.supabase_functions_url') || '/sync-calendar',
    body := '{}'::jsonb,
    headers := json_build_object(
      'Authorization', 'Bearer ' || current_setting('app.supabase_service_role_key'),
      'Content-Type', 'application/json'
    )::jsonb
  );
  $$
);

-- Sync Instagram posts daily at 03:00 UTC
select cron.schedule(
  'sync-posts',
  '0 3 * * *',
  $$
  select net.http_post(
    url := current_setting('app.supabase_functions_url') || '/sync-posts',
    body := '{}'::jsonb,
    headers := json_build_object(
      'Authorization', 'Bearer ' || current_setting('app.supabase_service_role_key'),
      'Content-Type', 'application/json'
    )::jsonb
  );
  $$
);
