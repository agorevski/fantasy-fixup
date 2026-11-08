# Evidence from FantasyPros only (Step 7)

The user wants **FantasyPros data only**. Do not use WebSearch. Do not fetch or cite any site outside the allowlist.

## Allowlist

- MCP tool results (`run_weekly`, `run_ros`, `player_news`, `grade_week`). These read `api.fantasypros.com`, `partners.fantasypros.com`, `mpbnfl.fantasypros.com`, and `www.fantasypros.com`.
- WebFetch of `https://www.fantasypros.com/...` pages only. Typical use is a player's page, from the `url` field in the run output (for example `https://www.fantasypros.com/nfl/players/<name>.php`), which carries FantasyPros' latest news and notes for that player.

## When to research

The report already contains the evidence the tool could gather. Research only to fill a `PROVISIONAL` move whose only missing item is `role` (see [pick-rules.md](pick-rules.md) section 5). Keep it to the players in those moves.

1. Call `player_news` with the two players' `fpId` values. It needs `FP_API_KEY`.
2. If that fails or returns nothing, WebFetch each player's FantasyPros page (the `url` from the report) and read the latest news item.
3. Use an item only if it is dated within the last 14 days and says something about the player's role: snaps, targets, carries, depth chart, or a QB change. Cite it as `FantasyPros, <date>: <headline>`.
4. If nothing qualifies, write `no recent reporting found` and leave the move provisional.

## Rules

- Do not invent reporting. Every cited item has a FantasyPros source and a date.
- Do not research players whose moves were held. The gate result stands.
- If research was skipped, say so in the report.
