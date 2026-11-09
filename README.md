# Fantasy Fixup

**You download the data. Your agent does the work for you.**

Fantasy Fixup reads FantasyPros rankings, projections, injuries, and news, plus your Yahoo league's roster and matchup, and tells you who to start, who to add, and who to drop. The advisor is **read-only**: it suggests moves but never changes your roster. You still have the final say.

Run it from the command line, or let Claude Code drive it through the `fantasy-lineup` MCP server and the `fantasy-fixup` skill.

## What it does

- **Weekly:** the best legal lineup for your league's slots, close calls settled by your matchup, and add/drop pairs that pass every gate (roster legality, availability, consensus, expert coverage). Each pair cites dated FantasyPros evidence.
- **Rest of season (ROS):** an add/drop view based on full consensus. Provisional until a weekly run confirms it.
- **Grade:** scores a past week's advice against actual points and keeps a season log.

Weekly rankings use the experts FantasyPros rates most accurate. The decision rules live in `decisions.py` and are covered by tests.

The separate **`yahoo-roster`** skill is the one part that changes a roster. It drives the Yahoo Fantasy app on an Android phone over ADB, and every change needs your explicit confirmation of the exact move.

## Project layout

```
.claude/skills/        Claude Code skills: fantasy-fixup (analysis), yahoo-roster (phone moves)
docs/                  FantasyPros API reference
src/fantasy_lineup/    Python package: advisor (CLI and report), decisions, lineup, rankings,
                       grade, web (website source), client, mcp_server, capture_addon, paths
tests/                 Unit tests (stdlib unittest)
var/                   Runtime state: cache, browser captures, saved session (gitignored)
.env                   Your settings and secrets (gitignored; template in .env.example)
.mcp.json              Registers the fantasy-lineup MCP server
```

## Requirements

- Python 3.10 or newer
- A FantasyPros account with a league synced to it
- A FantasyPros public API key from [the API key request page](https://secure.fantasypros.com/api-keys/request/)
- [mitmproxy](https://mitmproxy.org/), only for the one-time league capture
- [Claude Code](https://claude.com/claude-code), only for the MCP server and skills

## Setup

Run these from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # only for the website client
cp .env.example .env
```

Open `.env` and set `FP_API_KEY`. Keep secrets in `.env` only, never in code.

## Finding your league

The advisor needs your league key and team ID. If they are not already in `.env`, capture them once from your browser:

1. Run `mitmdump -s src/fantasy_lineup/capture_addon.py -p 8080`.
2. Point your browser at `localhost:8080` as a proxy and install the mitmproxy certificate.
3. Open your league's FantasyPros page so the roster data loads.
4. Run `PYTHONPATH=src python -m fantasy_lineup.advisor discover` to list teams, then `discover --team-id <id>` to save yours.

In Claude Code, the `list_league_teams` and `save_team` tools do the same.

## Configuration

Settings come from `.env` (see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `FP_SOURCE` | `api` | `api` (public API) or `web` (the FantasyPros website) |
| `FP_API_KEY` | none | Public API key. Required for `api`; recommended for `web` |
| `FP_LEAGUE_KEY` | none | League key, saved by `discover` |
| `FP_TEAM_ID` | `3` | Your team ID in the league |
| `FP_SEASON` | `2026` | NFL season year |
| `FP_WEEK` | current week | Week to analyze for the CLI `weekly` run |
| `FP_HEADLESS` | `true` | Set to `false` to show the browser in `client.py` |

On the web source, the expert set comes from the site's named accuracy lists, and injuries have no practice reports, so the DNP check does not run. Each source keeps its own snapshots, so comparisons never mix them.

## Usage

```bash
PYTHONPATH=src python -m fantasy_lineup.advisor weekly      # lineup, close calls, gated add/drops
PYTHONPATH=src python -m fantasy_lineup.advisor ros         # rest-of-season add/drop view
PYTHONPATH=src python -m fantasy_lineup.advisor grade 9     # grade week 9's advice
PYTHONPATH=src python -m unittest discover tests            # run the tests
```

Results are written to `var/cache/`. Responses are cached (rankings for 6 hours, injuries and news for 1 hour). The public API is rate limited; the client backs off on HTTP 429. HTTP 401 or 403 means `FP_API_KEY` is wrong or lacks access. Optional data that fails is noted in the report's **Data status** section, and missing injury data counts as unchecked, not out.

## Using with Claude Code

`.mcp.json` registers the `fantasy-lineup` server. Complete Setup first, and approve the project server when Claude Code asks. The server exposes tools for:

- Config and source: `check_config`, `current_source`, `set_source`, `set_web_session`
- League: `list_league_teams`, `save_team`
- Analysis: `run_weekly`, `run_ros`, `player_news`, `grade_week`, `season_log`, `list_snapshots`

The `fantasy-fixup` skill calls these in order: check config, run the analysis, report back.

## Privacy and security

- `.env`, `var/`, and `.venv/` are gitignored. `var/` holds session cookies, captured traffic, and API responses, so do not commit it.
- Files are written with mode `600`, and directories with mode `700`.
- `capture_addon.py` redacts cookie and auth headers in its log, but keeps the full auth headers in `var/capture/auth.json` so the session can be reused. Delete `var/capture/` when you are done.
- The password for website login is read from the environment and never stored or printed.

## Limitations

- Roster and league data come from endpoints the FantasyPros site uses, not the public API. They are undocumented and can break when the site changes.
- Recommendations are only as good as the rankings behind them. Close calls are judgment calls.
- Grades score the lineup as it stood at the last weekly run of that week.
- The advisor does not submit lineup or roster changes. Only the `yahoo-roster` skill does, after confirmation.
