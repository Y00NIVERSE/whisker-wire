# Deploying Whisker Wire with accounts

This turns on free accounts. Anyone can browse the wire, Value Radar and filings straight away, with no
login wall — a free account is only asked for at the two personal features, Ask Tick and Tick remembers,
and their watchlist and thesis notes then live under their account instead of a local file. Local/offline
mode (just running `python server.py` with nothing else set) is completely unaffected and still works
with no accounts.

I can't create these accounts for you (they're yours, and some ask for payment details even on a free
tier), so this part is on you. Everything after that, I already built and tested with mocks.

## 1. Supabase (accounts + database) — free

1. Create a project at [supabase.com](https://supabase.com) (free tier: 50,000 users, 500MB database, no card).
2. **Turn off email confirmation** so people can use the app right after signing up: Authentication →
   Sign In / Providers → Email → turn off "Confirm email". (You can turn this back on later; the app
   already handles the "check your email" case gracefully either way.)
3. Open the **SQL Editor** and run this once, exactly as written:

   ```sql
   create table public.profile (
     user_id uuid primary key references auth.users(id) on delete cascade,
     experience text,
     markets text[] not null default '{}'
   );
   create table public.watchlist (
     user_id uuid references auth.users(id) on delete cascade,
     symbol text not null,
     added_at timestamptz not null default now(),
     primary key (user_id, symbol)
   );
   create table public.thesis (
     id bigint generated always as identity primary key,
     user_id uuid references auth.users(id) on delete cascade,
     symbol text not null,
     name text,
     note text not null,
     invalidate_if text,
     review_below numeric,
     review_above numeric,
     snap jsonb,
     created_at timestamptz not null default now(),
     updated_at timestamptz not null default now()
   );
   alter table public.profile enable row level security;
   alter table public.watchlist enable row level security;
   alter table public.thesis enable row level security;
   create policy "own rows" on public.profile for all using (auth.uid() = user_id);
   create policy "own rows" on public.watchlist for all using (auth.uid() = user_id);
   create policy "own rows" on public.thesis for all using (auth.uid() = user_id);
   ```

4. Collect four values from **Project Settings → API**:
   - `SUPABASE_URL` — the Project URL
   - `SUPABASE_ANON_KEY` — the `anon` `public` key
   - `SUPABASE_SERVICE_KEY` — the `service_role` key (keep this one secret; it bypasses the row-security policies above)
   - `SUPABASE_JWT_SECRET` — under "JWT Settings", the legacy JWT secret (HS256)

## 2. Buttondown (mailing list) — free to 100 subscribers, optional

Only needed if you want the newsletter checkbox to do something. Skip this and the checkbox is simply
never shown as working — nothing else breaks.

1. Create an account at [buttondown.email](https://buttondown.email).
2. Settings → Programming → API Key. That's your `BUTTONDOWN_API_KEY`.

## 3. Render (hosting) — free, with a cold-start delay

1. Push this repository to GitHub (or GitLab).
2. On [render.com](https://render.com), New → Web Service, point it at the repo.
3. Settings:
   - **Root directory:** `whisker-wire`
   - **Build command:** (leave blank — standard library only, nothing to install)
   - **Start command:** `python server.py`
   - **Instance type:** Free
4. Environment variables (Render's dashboard, not committed anywhere):
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET` (from step 1)
   - `ALLOWED_HOSTS` = your Render URL's hostname, e.g. `whisker-wire.onrender.com` (add your custom domain here too, comma-separated, once you have one)
   - `BUTTONDOWN_API_KEY` (from step 2, if using it)
   - `SEC_USER_AGENT` = `Your Name your@email.com` — turns on the **Filings tab and the Company briefs** (annual-report numbers, red flags, latest 8-K developments) for every visitor, identifying you (the operator) to the SEC, as their automated-access rule requires. Use a real name and an email you read: the SEC may write to it if the site ever misbehaves. Without it, both tabs just say they are switched off, and everything else works.
5. Deploy. First load after any period of inactivity takes a few seconds to wake up (the free tier sleeps after 15 minutes idle) — that's expected, not a bug.

## Before sharing the link

- **Fill in `web/privacy.html`**: replace `REPLACE-WITH-YOUR-EMAIL` (two spots) and the "last updated" date. I wrote honest, plain-English content, but I'm not a lawyer — have someone check it against where your users actually are, especially since this app already reaches the EU (GDPR) and other markets with their own rules.
- **Decide whether "Forget everything" is enough.** Right now it clears a person's watchlist and notes but does not delete their Supabase login itself. If you want a real "delete my account" button, that's a small addition (an admin-key call to Supabase's user-delete endpoint) — say the word and I'll add it before you launch.
- **Test signup and login for real once your keys are in place.** I built and unit-tested every piece against mocks, and verified the gate/401/error-handling behaviour against a live server with fake credentials, but I have no way to create a real Supabase project myself, so the actual signup → email → login round trip needs one real run by you before you send the link to anyone.
