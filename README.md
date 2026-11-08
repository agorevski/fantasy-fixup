# FantasyPros Fixer

A small set of Python scripts that read FantasyPros expert rankings (from the official public API) and your league's roster, then suggest weekly lineup changes, waiver adds, and drops. The advisor is **read-only**: it never changes your roster.

## What it does

`fp_advisor.py` runs one of two analyses:

- **`weekly`**: start/sit suggestions, free agents worth adding, add/drop pairs, weekly best picks for QB/K/DST, and a FLEX check against last week's lineup. Each player is tagged with bye-week status, injury notes, and the median rank across the experts you trust.
- **`ros`**: rest-of-season add/drop suggestions.

Rankings are filtered to the experts that FantasyPros rates most accurate for each position group (QB/K/DST: top 10 for weekly and top 20 for ROS; FLEX: top 20 overall).

## Components

| File | Purpose |
| --- | --- |
| `fp_advisor.py` | The analysis. Run `weekly` or `ros`, or `discover` to find your league. Rankings, experts, and injuries come from the public API using `FP_API_KEY`. |
| `fp_client.py` | Standalone helper for logged-in FantasyPros sessions. `python fp_client.py login` opens a browser so you can sign in yourself, then saves the session cookies locally. `fp_advisor.py` does not currently use it. |
| `capture_addon.py` | mitmproxy addon that records your own browser's FantasyPros traffic. Used once to find your league key. |
| `fantasypros_v2_public.yml` | API reference for the FantasyPros endpoints. |
| `.claude/skills/fantasy-lineup/SKILL.md` | Instructions for running the weekly/ROS analysis through Claude Code. |

## Requirements

- Python 3.10 or newer
- A FantasyPros account with a league synced to it
- A FantasyPros public API key from [the API key request page](https://secure.fantasypros.com/api-keys/request/)
- [mitmproxy](https://mitmproxy.org/) only for the one-time league capture below (not in `requirements.txt`)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # only needed for fp_client.py
cp .env.example .env
```

Then open `.env` and set `FP_API_KEY` to your public API key. Keep the key in `.env` only. Do not put it in code or commit it.

## Finding your league

The public API does not expose league rosters, so the advisor needs your league's key and your team ID. Capture them from your browser once (you can skip this if `FP_LEAGUE_KEY` and `FP_TEAM_ID` are already in `.env`):

1. Start the capture proxy:
   ```bash
   mitmdump -s capture_addon.py -p 8080
   ```
2. Point your browser at `localhost:8080` as an HTTP/HTTPS proxy and install the mitmproxy certificate.
3. Open your league's FantasyPros page in that browser so it loads the league roster data.
4. List the teams in the captured league:
   ```bash
   python fp_advisor.py discover
   ```
5. Save your team:
   ```bash
   python fp_advisor.py discover --team-id <your team id>
   ```

This writes `FP_LEAGUE_KEY` and `FP_TEAM_ID` to `.env`.

## Configuration

Settings come from `.env` (see `.env.example`):

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `FP_API_KEY` | yes | none | FantasyPros public API key (sent as the `x-api-key` header) |
| `FP_LEAGUE_KEY` | yes | none | League key, saved by `discover` |
| `FP_TEAM_ID` | no | `3` | Your team ID in the league |
| `FP_SEASON` | no | `2026` | NFL season year, used by all API calls |
| `FP_WEEK` | no | current week | Week to analyze for `weekly` |
| `FP_HEADLESS` | no | `true` | Set to `false` to show the browser in `fp_client.py` |

## Usage

```bash
python fp_advisor.py weekly   # start/sit, waiver adds, drops, FLEX check
python fp_advisor.py ros      # rest-of-season adds and drops
```

Each run writes its results to `.fp_cache/`. Each weekly run also saves a snapshot to `.fp_cache/history/`, which the next week's run uses for the FLEX comparison. The first weekly run only saves a baseline, so the comparison appears after the second run.

The public API limits requests on the free tier. A run makes one call per expert, so an HTTP 429 means wait and retry. An HTTP 401 or 403 means `FP_API_KEY` is wrong or lacks access.

## Privacy and security

- `.env`, `.fp_session.json`, `.fp_capture/`, `.fp_cache/`, and `.venv/` are excluded by `.gitignore`. They can contain your league key, session cookies, and captured traffic. Do not commit them.
- Files the scripts create are written with mode `600`.
- `capture_addon.py` redacts cookie and auth headers in its request log, but it still stores the full auth headers in `.fp_capture/auth.json` so the session can be reused. Delete `.fp_capture/` when you are done.
- `fp_client.py` never reads or stores your password. You sign in yourself in the browser window.

## Limitations

- These scripts use FantasyPros endpoints that are not a documented public API. They can break when the site changes. Failures usually show up as "layout may have changed" or an HTTP error.
- Recommendations are only as good as the underlying rankings. Check injury news before you act on a suggestion.
- The advisor reads public rankings and league rosters. It does not submit lineup or roster changes.
