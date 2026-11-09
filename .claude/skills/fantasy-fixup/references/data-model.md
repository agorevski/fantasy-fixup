# Data model: sources, buckets, and output fields

Everything comes from FantasyPros.

## Data sources

The data source is set by `FP_SOURCE` in `.env`. The run tools read it on every call.

- `web` (recommended for the lineup): the FantasyPros website's own ranking endpoints, the same data the site shows. Needs a saved session, set up in [configuration.md](configuration.md).
- `api` (default): the official FantasyPros public API. Needs `FP_API_KEY`. The spec lists only waiver-wire (`WW`) rankings for in-season use, and those leave out rostered players. The tool asks for weekly rankings first and falls back to `WW`. If the Data status line says "the API served waiver-wire rankings", tell the user to use the web source for the lineup.

**With `FP_API_KEY` set, the web source also uses the API** for injuries (practice participation and play probability), FantasyPros news, and recent fantasy points. Without the key, the web source uses the site's injury table and moves lack role evidence.

The league comes from the FantasyPros My Playbook feeds (`FP_LEAGUE_KEY` and `FP_TEAM_ID`). Both sources use them. They provide:
- The starting slots and scoring (STD, PPR, or HALF). Rankings are requested in the league's scoring.
- Who owns whom.
- Your starters (with the slot each one fills) and your bench.
- The opponent, both projected totals, FantasyPros' win probability, and each game's status.

## Data buckets

**Bucket 1 (required):** the weekly cheat-sheet rankings for QB, K, DST, and FLEX, and the roster and matchup. If these fail, the run stops with an error.
- Weekly experts: the top 10 at QB, K, and DST, and the top 20 overall for FLEX, by accuracy.

**Bucket 2 (optional, never blocking):** everything else. When a piece is missing, the analysis still runs, and the Data status section says what is missing.
- The ROS consensus. This uses all experts: weekly accuracy lists leave only 2–3 ROS experts. Without it, add/drops are held (`ros_data`).
- The per-position weekly lists for RB, WR, and TE: projections and start/sit grades. Without them, FLEX projections fall back to the matchup feed.
- Injuries.
- Per-expert weekly lists. These are fetched only for groups with a candidate move, for the breadth check.
- News and recent points. These are fetched only for the players in candidate moves.

## Player fields

| Field | Meaning |
|---|---|
| `rank` | This week's consensus rank in the group (QB, K, DST, or FLX overall) |
| `rank_min` / `rank_max` | The best and worst rank any expert gave: the ceiling and the floor |
| `rank_ave`, `rank_std` | The average and spread of the expert ranks. A large spread means the experts disagree. |
| `proj`, `proj_src` | Projected points: FantasyPros rankings-to-projections, or the matchup feed's projection |
| `grade` | FantasyPros' start/sit grade for this week's matchup |
| `ros_rank`, `ros_ave` | The rest-of-season consensus rank and average |
| `bye`, `bye_now` | The bye week, and whether it is this week |
| `locked` | The player's game has started |
| `injury` | Status, injury, practice reports, play probability, update date, and comment. Empty means none listed. `lookup failed` means unchecked. |
| `owned_yahoo`, `ecr_delta` | Yahoo ownership %, and the rank change since the last update (rising or falling) |
| `url` | The player's FantasyPros page (allowed for WebFetch) |
| `fpId` | The FantasyPros player id. Pass it to `player_news`. |

## Periods, snapshots, and the season log

- The period is the NFL week the source reports, for example `week09`. `FP_WEEK` in `.env` overrides it.
- Results are saved to `var/cache/weekly.json` or `var/cache/weekly-web.json`. Each weekly run is also saved as a snapshot in `var/cache/history/` (or `history/web/`) as `weekly-weekNN.json`. Re-running in the same week overwrites that week's snapshot.
- `grade_week` scores a snapshot against actual points and writes `season-log.json` next to the snapshots. The snapshot records the lineup as it stood when the analysis ran. Run `run_weekly` after the user sets the lineup, so the grade compares against the lineup they actually played.
- Each source keeps its own snapshots and season log. Do not mix them.
