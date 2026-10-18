-- Supabase Database Schema for Pie Backtester

create table if not exists pies (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid references auth.users on delete cascade,
  name        text not null,
  is_public   boolean default false,
  is_example  boolean default false,
  config      jsonb not null,
  created_at  timestamptz default now()
);

-- Row-Level Security (RLS)
alter table pies enable row level security;

-- Policies
drop policy if exists "Public pies or owner read" on pies;
create policy "Public pies or owner read" on pies
  for select using (is_public = true or owner_id = auth.uid());

drop policy if exists "Owner insert" on pies;
create policy "Owner insert" on pies
  for insert with check (owner_id = auth.uid());

drop policy if exists "Owner update" on pies;
create policy "Owner update" on pies
  for update using (owner_id = auth.uid());

drop policy if exists "Owner delete" on pies;
create policy "Owner delete" on pies
  for delete using (owner_id = auth.uid());
