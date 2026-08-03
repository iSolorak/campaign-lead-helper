# Lead Research Dashboard

A personal, single-user Django dashboard for discovering local businesses,
reviewing their websites, recording notes, and sending manually reviewed outreach.
OpenStreetMap Overpass is the default free discovery source. Google Places is an
optional, disabled provider.

## Features

- Campaigns with per-run targets for leads with and without a website listed
- Idempotent Overpass discovery with exact and probable duplicate detection
- Mobile and desktop Google PageSpeed/Lighthouse history
- Limited, manual homepage inspection (no whole-site crawling)
- Search, filters, useful presets, follow-ups, notes, and outreach history
- Editable email drafts and explicit sending through Django's email backend
- Responsive shadcn-inspired dashboard protected by Django authentication
- SQLite by default; no Redis, Celery, or frontend framework

Provider HTTP code lives in `leads/providers/`; discovery, deduplication,
PageSpeed, inspection, and outreach logic live in focused `leads/services/`
modules. Views only coordinate forms and services. External calls never run in
models, migrations, or startup.

## Local setup

Python 3.13+ is recommended.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in with a staff account (a superuser is
staff automatically). Campaigns, leads, collection runs,
and email templates can all be managed from the normal dashboard. Django Admin
remains available at `/admin/` for maintenance, but is not needed day to day.

## Docker

The Docker setup runs migrations, collects static files, and starts Gunicorn
automatically. SQLite data—including dashboard API and SMTP settings—is kept in
a named Docker volume.

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Open <http://localhost:8000/>. Useful commands:

```bash
docker compose logs -f web
docker compose exec web python manage.py collect_leads
docker compose down
```

Use `docker compose down -v` only when you intentionally want to delete the
SQLite data volume. For deployment, set a strong `DJANGO_SECRET_KEY`, set
`DJANGO_DEBUG=False`, and configure `DJANGO_ALLOWED_HOSTS` in `.env`.

Important `.env` settings include `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`,
`DJANGO_ALLOWED_HOSTS`, and security settings. Provider endpoints, User-Agent,
Google keys, and email delivery are configured under **Settings** in the staff dashboard. Use a real
contact address in the outbound User-Agent. The application boots without any
Google key.

For production set `DJANGO_DEBUG=False`, use a long random secret, configure
exact allowed hosts and HTTPS at the reverse proxy, and use SMTP credentials from
environment variables rather than source control.

## Campaigns and discovery

Open **Campaigns → New campaign** in the dashboard. Example:

- Name: `Athens Hair Salons`
- Search term: `hair_salon`
- Location: `Athens`
- Country: `Greece`
- Provider: `OpenStreetMap Overpass`

Supported Overpass search terms are `hair_salon`, `clothing_shop`,
`beauty_salon`, `restaurant`, `cafe`, `dentist`, `photographer`, and
`accountant`. Common names such as `barber`, `barber shop`, `coffee`, and
`coffee shop` are automatically converted to the matching supported term. The
mapping is easy to extend in `leads/providers/overpass.py`.

Google Places campaigns may also define a free-text query such as `Bar near
Athens`. When present, this query is sent to Text Search instead of the
structured category query, with the campaign country appended when necessary.
Free-text ranking is determined by Google and does not guarantee popularity or
business quality.

Run discovery from the CLI:

```bash
.venv/bin/python manage.py collect_leads
```

Or open **Campaigns** in the dashboard and press **Collect now** on an active
campaign. Each run creates up to the configured target in each website group and
shows a summary. Exact source records can never be inserted twice.

The visual layer uses local design tokens and component styles inspired by
shadcn/ui, with Bootstrap's responsive grid underneath. shadcn/ui does not
publish a CSS CDN and its official components target JavaScript frameworks, so
no React dependency or unofficial shadcn CDN is used. Layouts stack on phones,
use multi-column grids on laptops/desktops, and expand their content width on
4K displays.

The dashboard defaults to dark mode. The header toggle stores the selected dark
or light theme in the Django session, so the choice remains in effect while that
session is active. All dashboard routes require `is_staff=True`; ordinary
authenticated accounts receive HTTP 403.

Optional sample campaigns:

```bash
.venv/bin/python manage.py seed_campaigns
```

Overpass area matching uses the campaign location as an administrative-area
name. Ambiguous or differently translated area names may need adjustment.

## PageSpeed and website inspection

Analyze leads that have a website listed:

```bash
.venv/bin/python manage.py analyze_pending_leads
.venv/bin/python manage.py refresh_lighthouse_scores --older-than-days 30
```

The PageSpeed API key is optional but recommended for quota reliability. Results
retain mobile and desktop history; failures are stored without inventing a zero
score. A single lead can also be refreshed from its detail page. Homepage
inspection is manual from the same page and is limited by robots.txt, response
size, redirects, timeouts, and public-URL safety checks.

## Email

Development defaults to Django's console backend, which prints messages instead
of sending them. To send real email, open **Settings** in the staff dashboard,
select SMTP, and enter the host, port, username, password, TLS/SSL choice, and
default sender address. Saved SMTP passwords are never rendered back into HTML.

Email addresses are entered or confirmed manually. Drafts remain fully editable
and require an explicit final send. A lead is marked **Contacted** only after the
email backend accepts the message. Failed attempts retain the subject/body and
error. Leads marked do-not-contact cannot be emailed. Instagram and phone
entries are manual history only.

Email templates support: `{business_name}`, `{category}`, `{city}`,
`{website_url}`, `{mobile_performance}`, and `{desktop_performance}`.

## Scheduling

Use cron for this MVP (paths are examples):

```cron
0 7 * * * cd /srv/lead-dashboard && /srv/lead-dashboard/.venv/bin/python manage.py collect_leads >> /var/log/lead-collector.log 2>&1
15 7 * * * cd /srv/lead-dashboard && /srv/lead-dashboard/.venv/bin/python manage.py analyze_pending_leads >> /var/log/lead-pagespeed.log 2>&1
```

## SQLite backup and tests

Stop writes briefly and use SQLite's backup command:

```bash
sqlite3 db.sqlite3 ".backup 'backup-$(date +%F).sqlite3'"
.venv/bin/python manage.py test
```

All external HTTP and email behavior is mocked or uses an in-memory backend in
tests; tests never contact real APIs. PostgreSQL would be the next choice for
multiple concurrent users, background workers, provider webhooks, or heavier
write concurrency.

## Enabling Google Places later

Google Places is disabled by default and is not required. To opt in, enable the
Places API (New), open **Settings** in the dashboard, enter the key, and enable
Google Places. Then select Google Places on a campaign. Missing/disabled configuration produces a
runtime campaign error, not a startup failure.

## Known limitations and responsible use

- OpenStreetMap coverage varies by location; use public Overpass instances politely.
- “No website listed” only means none appeared in the discovery source; it does not prove no website exists.
- Lighthouse scores fluctuate and do not determine whether a design is attractive or converts well.
- Probable duplicates are conservatively logged/skipped for manual review; fuzzy identity is not certainty.
- The user must manually verify businesses, contact details, and email recipients.
- The user is responsible for lawful outreach, consent requirements, and opt-out handling.
- This MVP is synchronous; long provider/analysis actions occupy the current web or command process.
