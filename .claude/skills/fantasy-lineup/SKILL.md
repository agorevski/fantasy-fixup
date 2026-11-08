---
name: fantasy-lineup
description: Weekly FantasyPros-based lineup, start/sit, waiver add, and drop analysis for the Yahoo league synced to FantasyPros. Builds the best legal lineup for the league's slots, settles close calls by the matchup, gates every add/drop on weekly and rest-of-season expert consensus with dated FantasyPros evidence, flags byes ahead, and grades past weeks. Uses FantasyPros data only. Read-only; it recommends moves and never changes the roster. Use when the user asks for weekly or rest-of-season lineup, waiver, or drop suggestions, or how last week's advice did.
---

# fantasy-lineup

Produces weekly (`weekly`) or rest-of-season (`ros`) suggestions for QB, RB/WR/TE (FLEX), K, and DST.

## Principles

- **Priority:** winning each week. `weekly` is the primary product. `ros` runs only when the user asks for it.
- **Read-only:** recommend moves; never change the roster. Tell the user which moves to make in Yahoo.
- **FantasyPros data only.** Every fact in the report comes from FantasyPros: the MCP tools, or a `fantasypros.com` page. Never use WebSearch or any other site. Details: [references/research.md](references/research.md).
- **MCP tools only:** drive every step through the `fantasy-lineup` server (defined in `.mcp.json`, implemented in `src/fantasy_lineup/`). Do not run Python through Bash.
- **The tool decides; you explain.** `run_weekly` computes the legal lineup, the close calls, and every add/drop gate in code. Report its verdicts. Do not recompute ranks or averages, and do not override a verdict. The one exception: you may promote a `PROVISIONAL` move if you fill its missing evidence item from a dated FantasyPros source (see [references/pick-rules.md](references/pick-rules.md) section 5), and you must say that you did.
- **Bucket 2 never blocks:** missing or rate-limited optional data does not stop the analysis. Do not wait on it or retry it in a loop.

## MCP tools

| Tool | Purpose |
|---|---|
| `check_config` | Step 0: which `.env` settings are present, and whether the web session is saved (presence only, never values) |
| `current_source` | Step 0: which data source runs, `api` or `web` (from `FP_SOURCE`) |
| `set_source` | Step 0: set `FP_SOURCE` to `api` or `web` after the user chooses |
| `set_web_session` | Step 0 (web source only): set up the logged-in session by approach, `mitmproxy` or `login` |
| `run_weekly` | Weekly analysis: lineup, close calls, gated add/drops (it loads ROS data itself); optional `week` |
| `run_ros` | Rest-of-season add/drop view (only when asked) |
| `player_news` | FantasyPros news for up to 6 player ids (the `fpId` values in the report). Needs `FP_API_KEY` |
| `grade_week` | Score a past week's advice with FantasyPros' actual points; updates the season log |
| `season_log` | Season totals: points the advice gained and points left on the bench |
| `list_league_teams` | League capture: league name and team IDs/names (no key returned) |
| `save_team` | League capture: save the user's team ID after they choose it |
| `list_snapshots` | Saved weekly snapshots, labeled by source |

Tool names may appear with the server prefix, for example `mcp__fantasy-lineup__run_weekly`.

## Workflow

1. **Configure.** Confirm settings and the data source before any call that touches the API, website, or league feed. Details: [references/configuration.md](references/configuration.md).
2. **League capture (only if needed).** Required when `FP_LEAGUE_KEY` or `FP_TEAM_ID` is missing. Details: [references/league-capture.md](references/league-capture.md).
3. **Grade last week (once per new week).** If `list_snapshots` shows a snapshot for a week that has been played and `FP_API_KEY` is set, call `grade_week` once. Put its one-line result at the end of the report. Skip it if it errors; it is optional.
4. **Run the analysis.** Call `run_weekly`. Call `run_ros` only if the user asks for a rest-of-season view. Handle errors per [references/troubleshooting.md](references/troubleshooting.md).
5. **Interpret the results.** Data sources, buckets, and fields: [references/data-model.md](references/data-model.md).
6. **Explain the decisions.** What each gate and verdict means: [references/pick-rules.md](references/pick-rules.md).
7. **Fill evidence (only for provisional moves).** From FantasyPros sources only: [references/research.md](references/research.md).
8. **Write the report.** Actions first: [references/report-format.md](references/report-format.md).
9. **State the caveats** that apply: [references/caveats.md](references/caveats.md).

Load only the reference files the current task needs. For a routine weekly run with configuration already confirmed, that is usually `pick-rules` and `report-format`.

## Timing

Recommend running at these points. The user can automate them with `/schedule`.

- **Tuesday or Wednesday, before waivers clear:** add/drop moves.
- **Saturday:** injury designations are final for most games.
- **Sunday, about 90 minutes before the early games:** the final lineup check.
- Thursday, Saturday, and Monday games lock their players at kickoff. The report marks those players `LOCKED`, and the lineup keeps them where they are.

## Secrets

`.env` is listed in `.gitignore`. Keep it that way. Never print, echo, quote, or commit its values, and never ask the user to paste a secret into chat.
