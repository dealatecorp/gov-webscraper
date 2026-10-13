# TenderDesk

## Supabase accounts and recommendations

TenderDesk uses Supabase Auth for both local and deployed sessions. The browser receives only the publishable key; the secret key remains server-only. Email/password sign-up supports email confirmation, password recovery, persistent token refresh, and optional authenticator-app MFA. Every data API, export, and PDF download validates the Supabase access token. The local SQLite service maps a verified Supabase identity to its saved interests and watchlist; Supabase passwords are never stored locally.

On Overview, expand **Edit your domains & interests**. Select multiple domains and/or comma-separated custom keywords. Recommendations match title, reference, organisation, category or description, exclude passed/unknown deadlines and corrigenda, and show matching terms. Matches are ordered by closing date, not ML relevance. Coverage is limited to the collected archive. Preferences and watchlists are user-specific; tender data, PDF cache and collector settings are shared. Legacy pre-login bookmarks remain preserved in the database but are not assigned to any new account.

For production, keep email confirmation enabled, configure a custom SMTP provider, add every deployed/local callback URL to the Supabase Auth redirect allow list, and enable leaked-password protection plus CAPTCHA in the Supabase dashboard. Users can enable or remove TOTP two-step verification from **Collection settings → Account security**.

## PDF downloads and rapid refresh

Open a notice and choose **Find & download PDFs**. Public PDFs are fetched on demand, validated by their PDF signature, and saved in SQLite. Download links serve the saved file directly with an attachment header; documents are limited to 25 MB each. Cached copies show their retrieval date and are not automatically replaced. Confirm later revisions on the official portal. GeM was live-tested successfully; sampled GePNIC document endpoints returned HTML instead of PDFs, so those documents remain unavailable without the portal's interactive flow. CAPTCHA and login are not bypassed.

The background collector targets a start every 30 seconds and the dashboard refreshes every 10 seconds. Slow cycles do not overlap. Failed feeds back off for 1–30 minutes. This does not expand the existing limited feed coverage or guarantee that upstream portals publish in real time. The Windows background task must remain running and the computer must be awake and online.

A local procurement dashboard with real public records from GeM, CPPP (eProcurement + ePublishing), Defproc, and Hindustan Shipyard. Python 3.11+ only; no pip or npm dependencies.

## Start

Set the public Supabase connection values, run `python app.py`, then open http://127.0.0.1:8765 . The secret/service key is not needed for the local SQLite server.

```powershell
$env:SUPABASE_URL='https://your-project-ref.supabase.co'
$env:SUPABASE_PUBLISHABLE_KEY='sb_publishable_...'
python app.py
```

The process starts a collection immediately and targets a collection start every 30 seconds by default (slow cycles do not overlap). Closing the browser does not stop collection. Keep the server running; a sleeping/offline computer cannot collect. `install-autostart.ps1` registers a per-user Windows logon task; it is an optional OS-level setup separate from the server's own scheduler. Stop a foreground server with Ctrl+C. Run `Stop-ScheduledTask -TaskName TenderDeskCollector` to stop a task-launched server. Remove its logon task with `Unregister-ScheduledTask -TaskName TenderDeskCollector -Confirm:$false` if no longer needed.

Open Collection settings to adjust the interval (30–86400 seconds), number of latest GeM pages (1–20), and rolling backfill pages (0–10). A manual sync queues the next cycle. Source failures are isolated and recorded. Startup recovers interrupted source states.

## Features

- Responsive dashboard, notice search, source/type/deadline filters, sorting and pagination.
- Table/card views, persistent watchlist, notice drawer, revision history and official links.
- CSV export of matching records (maximum 10,000), formula-injection escaping.
- SQLite WAL persistence of notices, events, settings, bookmarks and collection runs.
- Source health, explicit coverage notes, retry/backoff, collection timestamps, stale-data errors.
- Latest GeM listings plus a persisted rolling page cursor. Public session token is fetched dynamically and is not hardcoded.
- Existing verified probe samples are imported once on an empty database, with import events; they are not marked as a successful live collection.

## Files and storage

`app.py`: HTTP server, collectors, scheduler and storage. `web/`: buildless UI. `data/tenders.sqlite3`: application database. `data/app.log`: collector errors and run summaries. Set `TENDER_DATA_DIR` to change storage; set `PORT` to change the local port. Back up SQLite using its backup API, or stop the server before copying the database and WAL files.

The interface uses the navy/paper/gold design direction of the Vizag Chambers project and compact rounded panels inspired by Moto-Stock. Google fonts are optional; system fonts are the fallback.

## Coverage and semantics

This is an operational local MVP, not a complete mirror of the portals. GePNIC homepages expose limited recent windows (typically 10 tenders + 10 corrigenda). HSL uses `eprocurehsl.nic.in`. Records can be missed between polls or while offline. Full active-tender traversal, awards, cancellations, generic announcements, email delivery and all document downloads are not implemented. GeM's listing request is an undocumented website endpoint and can change.

GePNIC records use source + reference + notice type (and corrigendum title) for identity. Repeated corrigenda with exactly the same reference and title become revisions; the homepage lacks a stable unique amendment identifier. CPPP's two feeds remain separate. Session URL changes do not create false revision events. Data is not deleted when it disappears from a feed. Deadline-derived Open/Closed is not an official awarded/cancelled status. UI counters represent stored records, not total government tenders.

Dates display in IST. GeM's public listing JavaScript displays the literal UTC-looking clock fields with UTC formatting, so the collector interprets that displayed clock as IST. Always verify final deadlines on the official page. Public GePNIC homepage notice links omit the collector-only `session` parameter so the official portal can initialize a fresh browser session. Stored notice and revision links are repaired on startup. Document-download links and other session-bound forms are not rewritten.

## Vercel + Supabase deployment

The repository includes a Vercel Python Function (`api/index.py`) and `vercel.json`. It serves the frontend, verifies Supabase Auth access tokens, stores TenderDesk data in the isolated `tenderdesk_*` PostgreSQL tables, and stores PDFs in the private `tenderdesk-documents` bucket.

**Fetch latest tenders** performs a real collection for signed-in users, shows results/errors, and reloads notices and recommendations. A shared database lease prevents overlapping jobs across serverless instances. All users share a minimum 15-minute gap between collection starts. Existing data is retained when a portal fails.

Background collection uses **Supabase Cron**, because Vercel Hobby only permits daily native cron jobs. Apply `supabase/migrations/20261012111719_tenderdesk_collection_schedule.sql` to the intended Supabase project. The job `tenderdesk-15-minute-collection` checks eligibility once a minute and dispatches after the 15-minute gap (normally 15–16 minutes between starts). It continues with the browser closed. The URL in the migration is production-specific; change it for another deployment. No other project cron jobs are modified.

On the first production button click, the backend securely stores its existing `CRON_SECRET` in Supabase Vault using a service-role-only, security-invoker function. The scheduled request reads that value from Vault. No credential is exposed to the frontend or committed in SQL. Collection state and helper functions are inaccessible to anonymous/authenticated database clients. The backend authenticates users before allowing button-triggered collection.

Source requests are bounded and independent feeds run concurrently. Public listing windows are limited; remote blocking, CAPTCHA, timeouts, or portal changes appear in Data sources rather than fabricated tender data. Page coverage can be adjusted in Collection settings.

Before deployment, create the following Vercel environment variables for Production, Preview and Development. Copy the first two from Supabase **Connect**; generate a random `CRON_SECRET`. Keep the secret key server-only and never commit a `.env` file.

```text
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
CRON_SECRET=<long-random-value>
```

After applying the schema and collection migration, deploy the connected Vercel project. Configure Supabase Auth URL settings for the production URL and `/` callback, keep email confirmation enabled, then create an account in TenderDesk and click **Fetch latest tenders** to initialize the archive and scheduler credential.

## Tests

Run `python -m unittest discover -s tests -v`, `node --check web/app.js`, and `node --check web/session.js`. Tests use temporary databases, mocked Supabase identity responses, and saved public fixtures; no network requests are required.
