-- Shared server-only lease: prevents duplicate scrapes across Vercel instances.
create table if not exists public.tenderdesk_collection (
  id integer primary key check (id = 1),
  run_token uuid,
  started timestamptz,
  finished timestamptz,
  next_allowed_at timestamptz,
  lease_until timestamptz,
  results jsonb not null default '[]'::jsonb
);
alter table public.tenderdesk_collection enable row level security;
revoke all on public.tenderdesk_collection from public, anon, authenticated;
grant select, insert, update on public.tenderdesk_collection to service_role;
insert into public.tenderdesk_collection (id) values (1) on conflict do nothing;

create or replace function public.tenderdesk_claim_collection(run_token uuid)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare claimed integer;
begin
  update public.tenderdesk_collection c
  set run_token = $1, started = now(), finished = null,
      next_allowed_at = now() + interval '15 minutes',
      lease_until = now() + interval '6 minutes'
  where id = 1
    and (c.next_allowed_at is null or c.next_allowed_at <= now())
    and (c.lease_until is null or c.lease_until <= now());
  get diagnostics claimed = row_count;
  return claimed = 1;
end;
$$;
revoke all on function public.tenderdesk_claim_collection(uuid) from public, anon, authenticated;
grant execute on function public.tenderdesk_claim_collection(uuid) to service_role;

-- The production backend installs its existing cron credential directly into
-- Vault. No secret is in this migration, Git, the browser, or cron.job.command.
create or replace function public.tenderdesk_set_collection_secret(cron_secret text)
returns void language plpgsql security invoker set search_path = '' as $$
declare secret_id uuid;
begin
  if length(cron_secret) < 24 then
    raise exception 'Collection credential is not configured';
  end if;
  select id into secret_id from vault.secrets where name = 'tenderdesk_collection_cron';
  if secret_id is null then
    perform vault.create_secret(cron_secret, 'tenderdesk_collection_cron', 'TenderDesk collection endpoint only');
  else
    perform vault.update_secret(secret_id, cron_secret);
  end if;
end;
$$;
revoke all on function public.tenderdesk_set_collection_secret(text) from public, anon, authenticated;
grant execute on function public.tenderdesk_set_collection_secret(text) to service_role;

-- Check once per minute but dispatch only when the 15-minute cooldown expires.
-- This avoids skipped cycles caused by scheduler jitter or an intervening click.
select cron.schedule('tenderdesk-15-minute-collection', '* * * * *', $job$
  select net.http_get(
    url := 'https://gov-webscraper.vercel.app/api/collect',
    headers := jsonb_build_object('Authorization', 'Bearer ' || s.decrypted_secret),
    timeout_milliseconds := 240000
  )
  from vault.decrypted_secrets s
  where s.name = 'tenderdesk_collection_cron'
    and exists (
      select 1 from public.tenderdesk_collection c
      where c.id = 1 and (c.next_allowed_at is null or c.next_allowed_at <= now())
      and (c.lease_until is null or c.lease_until <= now())
    );
$job$);
