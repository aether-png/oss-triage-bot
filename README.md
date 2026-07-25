# OSS Triage Bot

A tiny, free, no-GPU weekly digest for finding **real** open source issues
worth your time — not typo fixes, not doc stubs, not issues that are
already crowded with comments.

Every day, it scans a repo list you curate, filters out weak issues
with cheap heuristics, then asks a free-tier LLM one focused question
per candidate: *does this look like it needs real investigation?*
Survivors get posted as a single digest issue in this repo.

## Why this exists

Good-first-issue pools in popular repos get picked over within hours.
Manually re-checking several repos every day doesn't scale, but
outsourcing the *judgment* of "is this worth my time" to a bot would
defeat the point. This only automates the scanning — you still do
every bit of the actual investigation, fix, and PR.

## Setup (5 minutes)

1. Fork or use this repo as a template.
2. Edit `repos.json` — list the repos you actually care about. Keep
   this curated by hand; it's the one part that shouldn't be automated.
3. (Optional but recommended) Add at least one free-tier API key as a
   repo secret under **Settings → Secrets and variables → Actions**:
   - `GROQ_API_KEY` — https://console.groq.com (fast, generous free tier)
   - `CEREBRAS_API_KEY` — https://cloud.cerebras.ai
   - `GEMINI_API_KEY` — https://aistudio.google.com/apikey
   - `OPENROUTER_API_KEY` — https://openrouter.ai (has free models)

   The bot tries providers in that order and falls back automatically.
   If you add none, it still runs — filtering drops to heuristics only.
4. Enable Actions on your fork if prompted. That's it — it runs weekly
   on the schedule in `.github/workflows/daily-triage.yml`, and you can
   trigger a manual run anytime from the **Actions** tab
   ("Run workflow").

## How filtering works

**Heuristics (always run, free):**
- issue is unassigned
- fewer than 5 comments (not already being worked)
- body is substantial (≥200 chars — filters out one-liners)
- not labeled duplicate/wontfix/invalid/stale

**LLM judgment (only for heuristic survivors, to stay in free-tier limits):**
A single yes/no question — does this look like it needs real
investigation, or is it cosmetic? Only "yes" issues make the digest.

## What this is not

- Not a claim-for-you bot. It never comments, assigns, or opens PRs.
- Not a ranking of "best" repos to contribute to — the repo list is
  yours to curate, on purpose.
- Not a guarantee of quality — it narrows the pool, you still read
  and decide.

## License

MIT
