---
name: fantasy-lineup
description: Weekly FantasyPros-based lineup, start/sit, waiver add, and drop analysis for the Yahoo league synced to FantasyPros, with bye, injury, per-expert pick, and week-over-week FLEX checks plus news-backed player notes. Read-only; it recommends moves and never changes the roster. Use when the user asks for weekly or rest-of-season lineup, waiver, or drop suggestions.
---

# fantasy-lineup

Produces weekly (`weekly`) or rest-of-season (`ros`) suggestions for QB, RB/WR/TE (FLEX), K, and DST.

## Principles

- **Priority:** winning each week. `weekly` is the primary product. `ros` runs only when the user asks for it.
- **Read-only:** recommend moves; never change the roster. Tell the user which moves to make in Yahoo.
- **MCP tools only:** drive every step through the `fantasy-lineup` server (defined in `.mcp.json`, implemented in `src/fantasy_lineup/mcp_server.py`). Do not run `advisor.py` (`python -m fantasy_lineup.advisor`) or other Python through Bash.
- **Bucket 2 never blocks:** missing or rate-limited optional data does not stop the analysis. Do not wait on it or retry it in a loop.
- **Web source: net-positive moves only.** When `FP_SOURCE=web`, every recommended add/drop or start/sit swap must be a net improvement in both the rest-of-season (ROS) expert consensus and the weekly expert consensus, and the roster must not get worse week over week. Recommend nothing that fails this gate, even if it looks good in the weekly data alone. Details: [references/pick-rules.md](references/pick-rules.md) section 7.
- **Every move is evidence-driven.** Each recommended move needs the evidence bundle in [references/pick-rules.md](references/pick-rules.md) section 8: expert breadth (not just the median), two-horizon agreement, availability, and dated role and matchup reporting. A move with missing evidence is provisional, and provisional moves are not recommended. Research for moves is required, which is the one exception to "bucket 2 never blocks".

## MCP tools

| Tool | Purpose |
|---|---|
| `check_config` | Step 0: which `.env` settings are present, and whether the web session is saved (presence only, never values) |
| `current_source` | Step 0: which data source runs, `api` or `web` (from `FP_SOURCE`) |
| `set_source` | Step 0: set `FP_SOURCE` to `api` or `web` after the user chooses |
| `set_web_session` | Step 0 (web source only): set up the logged-in session by approach, `mitmproxy` or `login` |
| `run_weekly` | Step 2: weekly analysis; optional `week` override |
| `run_ros` | Step 2: rest-of-season analysis (only when asked) |
| `list_league_teams` | League capture: league name and team IDs/names (no key returned) |
| `save_team` | League capture: save the user's team ID after they choose it |
| `list_snapshots` | Step 5: saved weekly snapshots used by the FLEX check, labeled by source |

Tool names may appear with the server prefix, for example `mcp__fantasy-lineup__run_weekly`.

## Workflow

1. **Configure.** Confirm settings and the data source before any call that touches the API, website, or league feed. Details: [references/configuration.md](references/configuration.md).
2. **League capture (only if needed).** Required when `FP_LEAGUE_KEY` or `FP_TEAM_ID` is missing. Details: [references/league-capture.md](references/league-capture.md).
3. **Run the analysis.** Call `run_weekly`. When `FP_SOURCE=web`, also call `run_ros` in the same turn, because the net-positive gate needs both. Call `run_ros` alone only if the user asks for ROS. Handle errors per [references/troubleshooting.md](references/troubleshooting.md).
4. **Interpret the results.** Understand the data buckets, sources, and output fields: [references/data-model.md](references/data-model.md).
5. **Apply the pick rules.** Byes, injuries, expert splits, and the FLEX week-over-week check: [references/pick-rules.md](references/pick-rules.md).
6. **Research (optional).** Add news for recommended players when time and rate limits allow: [references/research.md](references/research.md).
7. **Write the report.** Follow the templates in [references/report-format.md](references/report-format.md).
8. **State the caveats** that apply to the results: [references/caveats.md](references/caveats.md).

Load only the reference files the current task needs. For a routine weekly run with configuration already confirmed, that is usually `data-model`, `pick-rules`, and `report-format`.

## Secrets

`.env` is listed in `.gitignore`. Keep it that way. Never print, echo, quote, or commit its values, and never ask the user to paste a secret into chat.
