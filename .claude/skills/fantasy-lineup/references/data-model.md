# Data model: sources, buckets, and output fields

## Data sources

The data source is set by `FP_SOURCE` in `.env`. The run tools read it on every call.

- `api` (default): the official FantasyPros public API. Needs `FP_API_KEY`.
- `web`: the FantasyPros website's own endpoints, the same data the site shows. Needs a saved session, set up in [configuration.md](configuration.md).

The league roster comes from the FantasyPros league feed, which needs `FP_LEAGUE_KEY` and `FP_TEAM_ID`. Both sources use it.

The report's first lines say which source ran. The two sources are meant to be compared. When the user asks why a result differs, run both sources and compare the lineup tables. Do not mix their FLEX snapshots: each source keeps its own history.

## Data buckets

Data falls into two buckets, used in this order.

**Bucket 1 (required): cheat-sheet rankings and the roster.**
- Weekly: QB, K, DST, and FLEX cheat-sheet rankings, plus the bye weeks they carry. QB, K, and DST use the top 10 experts for that position. FLEX uses the top 20 overall. Experts are ranked by the API's `accuracy_weekly` score for each position.
- ROS: the same groups from the ROS rankings. QB, K, and DST use the top 20 experts. FLEX uses the top 20 overall.
- The roster (starters and bench) from the league feed.

**Bucket 2 (optional, never blocking): everything else.** Individual injury reports, per-expert picks and medians, and news. Use them when present. If they are missing or rate limited, the analysis still proceeds on bucket 1. The report's **Data status** section says what was missing.

## Output fields

Each roster and top free-agent row includes:

- `bye`: the bye week, or `BYE THIS WEEK` (bucket 1).
- `injury` (bucket 2): status, injury type, practice reports, and comments from the API.
  - An empty list means no injury is listed. It does not confirm the player is healthy.
  - A `lookup failed` entry means the injury data was not fetched. The status is `unchecked`.
- `expert_median` and `expert_picks` (bucket 2): each expert's rank for the player. `experts checked X/Y` means only X of Y expert lookups finished.
- `url`: the player's FantasyPros page.

## Periods and snapshots

- The period is the NFL week the API reports, for example `week09`. `FP_WEEK` in `.env` overrides it.
- Results are saved to `var/cache/<kind>.json`. Each weekly run is also saved as a snapshot in `var/cache/history/weekly-<period>.json`. Call `list_snapshots` to see them.
- Snapshots record the lineup as it stood when the analysis ran. Run `run_weekly` after the user has set their lineup for the week, so the next week's comparison is against the lineup they actually played.
