# FantasyPros Fixer

A small Python package that reads FantasyPros expert rankings (from the official public API) and your league's roster, then suggests weekly lineup changes, waiver adds, and drops. The advisor is **read-only**: it never changes your roster.

It can be run from the command line, or through Claude Code using the `fantasy-lineup` MCP server and skill.

## What it does

`advisor` runs one of two analyses:

- **`weekly`**: start/sit suggestions, free agents worth adding, add/drop pairs, weekly best picks for QB/K/DST, and a FLEX check against last week's lineup. Each player is tagged with bye-week status, injury notes, and the median rank across the experts you trust. Best picks and the FLEX check skip players on a bye that week, and free agents who are out or not practicing are never recommended.
- **`ros`**: rest-of-season add/drop suggestions.

Rankings are filtered to the experts that FantasyPros rates most accurate for each position group (QB/K/DST: top 10 for weekly and top 20 for ROS; FLEX: top 20 overall).

## Project layout

```
.
├── .claude/skills/fantasy-lineup/   Claude Code skill: SKILL.md and on-demand references/
├── docs/
│   └── fantasypros_v2_public.yml    FantasyPros API reference
├── src/fantasy_lineup/              Python package (all source code)
│   ├── advisor.py                   The analysis and the CLI (weekly, ros, discover)
│   ├── web.py                       The website data source (FP_SOURCE=web)
│   ├── client.py                    Playwright client for logged-in website sessions
│   ├── mcp_server.py                MCP server that exposes the advisor as tools
│   ├── capture_addon.py             mitmproxy addon that records your browser's traffic
│   └── paths.py                     Single source of truth for file locations
├── var/                             Runtime state, created by the tools (gitignored)
│   ├── cache/                       API and website responses, weekly results, history snapshots
│   ├── capture/                     Browser capture output
│   └── session.json                 Saved website session (mode 600)
├── .env                             Your settings and secrets (gitignored)
├── .env.example                     Template for .env
├── .mcp.json                        Registers the fantasy-lineup MCP server
├── requirements.txt                 Python dependencies
└── README.md
```

## Components

| Path | Purpose |
| --- | --- |
| `src/fantasy_lineup/advisor.py` | The analysis. Run `weekly` or `ros`, or `discover` to find your league. Rankings, experts, and injuries come from the public API using `FP_API_KEY`, or from the website when `FP_SOURCE=web`. |
| `src/fantasy_lineup/web.py` | The website data source (`FP_SOURCE=web`). Reads the site's own rankings, expert groups, and injury table, and manages the saved website session. |
| `src/fantasy_lineup/mcp_server.py` | MCP server that exposes the advisor as tools for Claude Code. It wraps `advisor.py`; all analysis logic stays there. See [Using with Claude Code](#using-with-claude-code). |
| `.mcp.json` | Registers the `fantasy-lineup` MCP server for this project. |
| `src/fantasy_lineup/client.py` | Standalone helper for logged-in FantasyPros sessions. `python -m fantasy_lineup.client login` opens a browser so you can sign in yourself, then saves the session cookies locally. `advisor.py` does not currently use it. |
| `src/fantasy_lineup/capture_addon.py` | mitmproxy addon that records your own browser's FantasyPros traffic. Used once to find your league key. |
| `src/fantasy_lineup/paths.py` | Defines every file and directory location the package uses. |
| `docs/fantasypros_v2_public.yml` | API reference for the FantasyPros endpoints. |
| `.claude/skills/fantasy-lineup/SKILL.md` | Instructions for running the weekly/ROS analysis through Claude Code. |

## Requirements

- Python 3.10 or newer
- A FantasyPros account with a league synced to it
- A FantasyPros public API key from [the API key request page](https://secure.fantasypros.com/api-keys/request/)
- [mitmproxy](https://mitmproxy.org/) only for the one-time league capture below (not in `requirements.txt`)
- [Claude Code](https://claude.com/claude-code), only if you want to use the MCP server or the skill

## Setup

Run these from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # only needed for the website client (client.py)
cp .env.example .env
```

`requirements.txt` installs `python-dotenv` and `mcp` (for the MCP server), and `playwright` (for `client.py`).

Then open `.env` and set `FP_API_KEY` to your public API key. Keep the key in `.env` only. Do not put it in code or commit it.

## Running the code

The package lives in `src/`, so put `src` on the import path and run modules with `-m`:

```bash
PYTHONPATH=src python -m fantasy_lineup.advisor weekly
```

The MCP registration in `.mcp.json` sets `PYTHONPATH` for you.

## Finding your league

The public API does not expose league rosters, so the advisor needs your league's key and your team ID. Capture them from your browser once (you can skip this if `FP_LEAGUE_KEY` and `FP_TEAM_ID` are already in `.env`):

1. Start the capture proxy:
   ```bash
   mitmdump -s src/fantasy_lineup/capture_addon.py -p 8080
   ```
2. Point your browser at `localhost:8080` as an HTTP/HTTPS proxy and install the mitmproxy certificate.
3. Open your league's FantasyPros page in that browser so it loads the league roster data.
4. List the teams in the captured league:
   ```bash
   PYTHONPATH=src python -m fantasy_lineup.advisor discover
   ```
5. Save your team:
   ```bash
   PYTHONPATH=src python -m fantasy_lineup.advisor discover --team-id <your team id>
   ```

This writes `FP_LEAGUE_KEY` and `FP_TEAM_ID` to `.env`. In Claude Code, the `list_league_teams` and `save_team` tools do steps 4 and 5.

## Configuration

Settings come from `.env` (see `.env.example`):

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `FP_SOURCE` | no | `api` | Data source: `api` (public API) or `web` (the FantasyPros website). The MCP server reads it on every call. |
| `FP_API_KEY` | for `api` | none | FantasyPros public API key (sent as the `x-api-key` header) |
| `FANTASYPROS_USERNAME` / `FANTASYPROS_PASSWORD` | for web login | none | Website sign-in, used only by the `login` session approach |
| `FP_LEAGUE_KEY` | yes | none | League key, saved by `discover` |
| `FP_TEAM_ID` | no | `3` | Your team ID in the league |
| `FP_SEASON` | no | `2026` | NFL season year, used by all API calls |
| `FP_WEEK` | no | current week | Week to analyze for `weekly`. When unset, the week the FantasyPros feed is currently serving is used. |
| `FP_HEADLESS` | no | `true` | Set to `false` to show the browser in `client.py` |

## Web source (`FP_SOURCE=web`)

The web source reads the same kinds of data from the website, so the two sources can be compared.

- Rankings and expert groups come from `partners.fantasypros.com/api/v1/` (`consensus-rankings.php` and `expert-groups.php`). These work without a login.
- The current week comes from the QB rankings page. Injuries come from the site's injury table.
- The expert set is the site's named accuracy list (for example "Top 10 QB"). The public API picks the top N by a numeric score, so the two sets can differ.
- The injury table has only the status and the injury. It has no practice reports or comments, so the DNP check does not run on this source.

Each source keeps its own weekly snapshots (`var/cache/history/` for the API, `var/cache/history/web/` for the website), so FLEX comparisons never mix them. Its output goes to `var/cache/weekly-web.json`.

A saved website session (`var/session.json`, mode 600) is attached to requests when it exists. There are two ways to create it:

- `mitmproxy` (default): capture a signed-in browser session with `src/fantasy_lineup/capture_addon.py`. The capture is imported into `var/session.json`, and `var/capture/auth.json` is deleted.
- `login`: sign in with `FANTASYPROS_USERNAME` and `FANTASYPROS_PASSWORD` from `.env`. This opens a visible browser window, so a verification check can be completed by hand. The password is read from the environment and is never printed or stored.

## Usage

```bash
PYTHONPATH=src python -m fantasy_lineup.advisor weekly   # start/sit, waiver adds, drops, FLEX check
PYTHONPATH=src python -m fantasy_lineup.advisor ros      # rest-of-season adds and drops
```

Each run writes its results to `var/cache/weekly.json` or `var/cache/ros.json`. Each weekly run also saves a snapshot to `var/cache/history/`, which the next week's run uses for the FLEX comparison. The first weekly run only saves a baseline, so the comparison appears after the second run.

Responses from the API are cached under `var/cache/api/`: rankings for 6 hours and injury reports for 1 hour. Expert lists are always fetched fresh.

Injury and per-expert lookups are optional. If one fails, the run still completes, and the report's **Data status** section says what is missing. Missing injury data is treated as unchecked, not as out.

The public API limits requests on the free tier. The client waits at least 1.5 seconds between live calls and retries HTTP 429 responses up to 3 times with backoff. If a required wait would exceed 120 seconds, the run stops. Cached responses are kept, so run again later. An HTTP 401 or 403 means `FP_API_KEY` is wrong or lacks access.

## Using with Claude Code

`.mcp.json` registers the `fantasy-lineup` server, which runs `.venv/bin/python -m fantasy_lineup.mcp_server` with `PYTHONPATH=src`. Complete Setup first so that the virtual environment exists. Claude Code asks you to approve project servers the first time.

The server exposes these tools:

| Tool | What it does |
| --- | --- |
| `check_config` | Reports whether the `.env` settings are set, and whether the web session is saved. Returns true/false only, never the values. |
| `current_source` | Reports the data source, `api` or `web`. |
| `set_source` | Writes `FP_SOURCE` to `.env`. |
| `set_web_session` | For the web source: sets up the session by approach, `mitmproxy` (import the capture) or `login` (`.env` credentials). |
| `list_league_teams` | Lists the league and its teams from the captured feed. Does not return the league key. |
| `save_team` | Saves your team ID and the league key to `.env`. |
| `run_weekly` | Runs the weekly analysis and returns the report. Optional `week` argument. Streams progress while it runs. |
| `run_ros` | Runs the rest-of-season analysis and returns the report. |
| `list_snapshots` | Lists the saved weekly snapshots used by the FLEX check. |

The `fantasy-lineup` skill calls these tools in order: check config, run the analysis, and report back.

## Privacy and security

- `.env`, `var/`, and `.venv/` are excluded by `.gitignore`. `var/` holds your session cookies, captured traffic, and API responses, and can include your league key. Do not commit them.
- `.mcp.json` contains no secrets.
- Files the scripts create are written with mode `600`, and directories with mode `700`.
- `src/fantasy_lineup/capture_addon.py` redacts cookie and auth headers in its request log, but it still stores the full auth headers in `var/capture/auth.json` so the session can be reused. Delete `var/capture/` when you are done.
- `client.py` never reads or stores your password. You sign in yourself in the browser window.

## Limitations

- Roster and league data come from the same endpoints the FantasyPros site uses, not from the public API. These are not documented and can break when the site changes. Failures usually show up as an HTTP error in the output.
- Recommendations are only as good as the underlying rankings. Check injury news before you act on a suggestion.
- The advisor reads public rankings and league rosters. It does not submit lineup or roster changes.
