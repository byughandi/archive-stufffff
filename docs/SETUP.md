# Going live — what you do once (about 30 minutes)

Everything is built to deploy from GitHub Actions. Nothing here runs on your computer.
Dashboard labels change; where a click path differs, look for the same idea nearby.

## 1. GitHub repository
Create an empty repository named `grail-radar` and push this folder to its `main` branch.

Public or private is your call:
- **Public (recommended):** standard GitHub-hosted runners are free without a minute cap,
  so the 10-minute schedule costs nothing. The code, the taxonomy and CI logs are visible to
  anyone. The database, your feedback, the secrets and the site are not.
- **Private:** the free plan includes a limited number of Actions minutes per month, which a
  10-minute schedule exhausts within days. Either slow `scrape-fast` to every 2 hours and
  `scrape-slow` to every 6 (edit the two cron lines), or run the same commands from a small
  VM with cron.

## 2. Turso (database)
1. Sign up at turso.tech, create a database named `grail-radar` in a region near
   `us-east` (close to GitHub's runners).
2. Copy its URL (`libsql://grail-radar-<you>.turso.io`) and create a read/write token.

## 3. Cloudflare (site + API + login)
1. Create an API token from the "Edit Cloudflare Workers" template. Note your Account ID.
2. After the first deploy (step 6), open the `grail-radar` Worker → Settings → Domains &
   Routes and enable **Cloudflare Access** for its `workers.dev` address. Add a policy that
   allows only your email.
3. In Zero Trust → Access → Applications, open the application that was created and copy its
   **Application Audience (AUD) tag**. Your team domain looks like
   `<team>.cloudflareaccess.com`.

Until step 3 is done the API answers every request with "Cloudflare Access is not
configured" on purpose: it fails closed.

## 4. ntfy (phone alerts)
Install the ntfy app. Subscribe to a topic with a long random name, for example
`grail-radar-` followed by 20 random characters. Anyone who knows the name can read the
alerts, so treat it like a password.

## 5. Apify (weekly Instagram trends, scraping fallback)
Sign up for the free plan and copy your API token. The pipeline stops calling Apify at 90%
of the $5 monthly credit.

## 6. Tell GitHub
Repository → Settings → Secrets and variables → Actions.

| Secret | Value |
|---|---|
| `TURSO_DATABASE_URL` | the `libsql://…` URL |
| `TURSO_AUTH_TOKEN` | the Turso token |
| `CLOUDFLARE_API_TOKEN` | the Workers token |
| `CLOUDFLARE_ACCOUNT_ID` | your Cloudflare account id |
| `NTFY_TOPIC` | your topic name |
| `APIFY_TOKEN` | your Apify token |
| `GRAILED_ALGOLIA_APP_ID`, `GRAILED_ALGOLIA_KEY` | optional; see RUNBOOK "Grailed" |

| Variable | Value |
|---|---|
| `SITE_URL` | `https://grail-radar.<your-subdomain>.workers.dev` |
| `ACCESS_TEAM_DOMAIN` | `<team>.cloudflareaccess.com` |
| `ACCESS_AUD` | the AUD tag from step 3 |
| `ALLOWED_EMAIL` | your email (a second check inside the Worker) |

## 7. First runs, in this order (Actions tab → pick the workflow → Run workflow)
1. **Deploy**: creates the tables, builds the site, deploys the Worker.
2. Do Cloudflare step 3, set the three Access variables, run **Deploy** again.
3. **Scrape slow**: first Japanese listings. Check the Sources page on the site.
4. **Comps daily**: first sold prices and fair values.
5. **Scrape fast**: first Grailed run. If Sources shows Grailed as blocked, see the RUNBOOK.
6. **Trends weekly**: first Instagram pull (uses Apify credit).

After that the schedules take over. Open the site on your phone, add it to the home screen,
and start tapping Yes / No on cards: that is what trains the ranking.

## 8. Weekly brain refresh
In Claude Code, with this repository attached, create a weekly scheduled task with the
prompt: `Read docs/BRAIN_REFRESH.md and follow it.` It runs on your Claude subscription and
opens a pull request for you to skim.
