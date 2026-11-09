# FantasyPros Fixer

A small Python package that reads FantasyPros expert rankings, projections, injuries, and news, plus your league's roster and matchup, then suggests weekly lineup changes, waiver adds, and drops. Every input comes from FantasyPros. The advisor is **read-only**: it never changes your roster.

It can be run from the command line, or through Claude Code using the `fantasy-lineup` MCP server and the `fantasy-fixup` skill.

## What it does

`advisor` runs one of two analyses:

- **`weekly`**:
  - The best **legal** lineup for your league's starting slots, read from the league feed. Players whose game has started stay locked.
  - Close calls settled by your matchup: FantasyPros' win probability decides between ceiling and floor.
  - Add/drop pairs that pass every gate: roster legality, availability, weekly and rest-of-season consensus, a noise margin, expert coverage, and expert breadth. Each pair carries dated FantasyPros evidence.
  - The net change, the roster trend, byes ahead, streaming options, and free agents to watch.
- **`ros`**: a rest-of-season add/drop view, provisional until a weekly run confirms it.
- **`grade`**: scores a past week's advice with FantasyPros' actual points (actual vs recommended vs best possible) and keeps a season log.

Weekly rankings use the experts FantasyPros rates most accurate (QB/K/DST: the top 10 at the position; FLEX: the top 20 overall). ROS rankings use the full consensus, because most accurate weekly experts publish no ROS ranks. The decision rules live in `decisions.py` and are covered by tests.

## Project layout

```
.
├── .claude/skills/fantasy-fixup/    Claude Code skill: SKILL.md and on-demand references/
├── docs/
│   └── fantasypros_v2_public.yml    FantasyPros API reference
├── src/fantasy_lineup/              Python package (all source code)
│   ├── advisor.py                   Data loading, the report, and the CLI (weekly, ros, grade, discover)
│   ├── decisions.py                 Lineup plan, close calls, add/drop gates, net change, lookahead
│   ├── lineup.py                    Slot parsing, roster legality, and the best legal lineup
│   ├── rankings.py                  Parsing shared by the API and website sources
│   ├── grade.py                     Grades past weeks and keeps the season log
│   ├── web.py                       The website data source (FP_SOURCE=web)
│   ├── client.py                    Playwright client for logged-in website sessions
│   ├── mcp_server.py                MCP server that exposes the advisor as tools
│   ├── capture_addon.py             mitmproxy addon that records your browser's traffic
│   └── paths.py                     Single source of truth for file locations
├── tests/                           Unit tests (stdlib unittest, no network)
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
| `src/fantasy_lineup/advisor.py` | Loads the data and prints the report. Run `weekly`, `ros`, `grade [week]`, or `discover` to find your league. Rankings come from the public API using `FP_API_KEY`, or from the website when `FP_SOURCE=web`. |
| `src/fantasy_lineup/decisions.py` | The decision rules: the lineup plan, close calls and the matchup stance, the add/drop gates and evidence, net change, trend, and bye lookahead. |
| `src/fantasy_lineup/lineup.py` | League slots, roster legality (can the roster fill every slot?), and the best legal lineup. |
| `src/fantasy_lineup/rankings.py` | Turns consensus-ranking entries from either source into the same player fields. |
| `src/fantasy_lineup/grade.py` | Grades a saved week against actual FantasyPros points and writes `season-log.json`. |
| `src/fantasy_lineup/web.py` | The website data source (`FP_SOURCE=web`). Reads the site's own rankings, expert groups, and injury table, and manages the saved website session. |
| `src/fantasy_lineup/mcp_server.py` | MCP server that exposes the advisor as tools for Claude Code. It wraps `advisor.py`; all analysis logic stays there. See [Using with Claude Code](#using-with-claude-code). |
| `.mcp.json` | Registers the `fantasy-lineup` MCP server for this project. |
| `src/fantasy_lineup/client.py` | Standalone helper for logged-in FantasyPros sessions. `python -m fantasy_lineup.client login` opens a browser so you can sign in yourself, then saves the session cookies locally. `advisor.py` does not currently use it. |
| `src/fantasy_lineup/capture_addon.py` | mitmproxy addon that records your own browser's FantasyPros traffic. Used once to find your league key. |
| `src/fantasy_lineup/paths.py` | Defines every file and directory location the package uses. |
| `docs/fantasypros_v2_public.yml` | API reference for the FantasyPros endpoints. |
| `.claude/skills/fantasy-fixup/SKILL.md` | Instructions for running the weekly/ROS analysis through Claude Code. |

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
| `FP_API_KEY` | for `api`; recommended for `web` | none | FantasyPros public API key (sent as the `x-api-key` header). On the web source it adds practice reports, news, recent points, and grading. |
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
PYTHONPATH=src python -m fantasy_lineup.advisor weekly      # lineup, close calls, gated add/drops
PYTHONPATH=src python -m fantasy_lineup.advisor ros         # rest-of-season add/drop view
PYTHONPATH=src python -m fantasy_lineup.advisor grade 9     # grade week 9's advice (needs FP_API_KEY)
PYTHONPATH=src python -m unittest discover tests            # run the tests
```

Each run writes its results to `var/cache/weekly.json` or `var/cache/ros.json` (`-web` suffix for the website source). Each weekly run also saves a snapshot to `var/cache/history/`. The next run uses it for the trend line, and `grade` scores it after the games. `grade` writes `season-log.json` next to the snapshots.

Responses are cached under `var/cache/api/` and `var/cache/web/`: rankings for 6 hours, and injuries and news for 1 hour. Expert lists from the API are always fetched fresh.

Only the weekly cheat-sheet rankings, the roster, and the matchup are required. Everything else is optional: ROS rankings, per-position projections, injuries, per-expert lists (fetched only for groups with a candidate move), news, and recent points. If an optional piece fails, the run still completes, and the report's **Data status** section says what is missing. Missing injury data is treated as unchecked, not as out.

The public API limits requests on the free tier. The client waits at least 1.5 seconds between live calls and retries HTTP 429 responses for required data up to 3 times with backoff. Optional lookups do not retry. After a 429 that does not clear, further live API calls fail fast for 10 minutes. Cached responses are kept, so run again later. An HTTP 401 or 403 means `FP_API_KEY` is wrong or lacks access.

The public API spec documents only waiver-wire (`WW`) rankings for in-season use, and those leave out rostered players. The advisor asks for `WEEKLY` rankings first and falls back to `WW` with a Data status warning. The website source ranks every player, so it is the better choice for the lineup.

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
| `run_ros` | Runs the rest-of-season add/drop view and returns the report. |
| `player_news` | FantasyPros news for up to 6 player ids. Needs `FP_API_KEY`. |
| `grade_week` | Grades a past week against actual points and updates the season log. Needs `FP_API_KEY`. |
| `season_log` | Season totals of graded weeks. |
| `list_snapshots` | Lists the saved weekly snapshots. |

The `fantasy-fixup` skill calls these tools in order: check config, run the analysis, and report back.

## Privacy and security

- `.env`, `var/`, and `.venv/` are excluded by `.gitignore`. `var/` holds your session cookies, captured traffic, and API responses, and can include your league key. Do not commit them.
- `.mcp.json` contains no secrets.
- Files the scripts create are written with mode `600`, and directories with mode `700`.
- `src/fantasy_lineup/capture_addon.py` redacts cookie and auth headers in its request log, but it still stores the full auth headers in `var/capture/auth.json` so the session can be reused. Delete `var/capture/` when you are done.
- `client.py` never reads or stores your password. You sign in yourself in the browser window.

## Limitations

- Roster and league data come from the same endpoints the FantasyPros site uses, not from the public API. These are not documented and can break when the site changes. Failures usually show up as an HTTP error in the output.
- Recommendations are only as good as the underlying rankings and projections. Close calls are judgment calls.
- Grades score the lineup as it stood at the last weekly run of that week; later lineup edits are not seen.
- The advisor reads public rankings and league rosters. It does not submit lineup or roster changes.
