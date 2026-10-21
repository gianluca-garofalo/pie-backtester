-- Supabase Database Schema for Pie Backtester
--
-- The app reads and writes this table only from the Streamlit server, using the
-- service key, and scopes every query to the signed-in user itself. owner_id is the
-- app's user id ("google:<sub>" from Streamlit's Google sign-in), not a Supabase Auth user.
-- Row-level security stays on with no policies, so the public anon key can do nothing.

create table if not exists pies (
  id          uuid primary key default gen_random_uuid(),
  owner_id    text not null,
  name        text not null,
  is_public   boolean not null default false,
  is_example  boolean not null default false,
  config      jsonb not null,
  created_at  timestamptz default now()
);

create index if not exists pies_owner_id_idx on pies (owner_id);

alter table pies enable row level security;

-- Upgrading from the earlier schema (owner_id uuid referencing auth.users, per-user policies)
drop policy if exists "Public pies or owner read" on pies;
drop policy if exists "Owner insert" on pies;
drop policy if exists "Owner update" on pies;
drop policy if exists "Owner delete" on pies;
alter table pies drop constraint if exists pies_owner_id_fkey;
alter table pies alter column owner_id type text;
