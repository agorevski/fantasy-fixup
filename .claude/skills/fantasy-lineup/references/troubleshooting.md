# Running the analysis: error handling (Step 4)

Run `run_weekly` or `run_ros` only after [configuration.md](configuration.md) is confirmed.

If the tool returns the report, go to [pick-rules.md](pick-rules.md) and [report-format.md](report-format.md).

| Result | Action |
|---|---|
| A `Data status` section listing missing optional data | **Not an error.** Use what is there, and say what is missing. |
| `role evidence unavailable` or `rate limited ... skipped` | Optional. Moves stay provisional. Offer the FantasyPros page check in [research.md](research.md), or a rerun later. Do not loop. |
| `the API served waiver-wire rankings` | The API source cannot rank rostered players. Suggest `set_source` to `web` (with the user's agreement), then run again. |
| `ERROR` with `FP_API_KEY missing` | Go back to Step 0 in [configuration.md](configuration.md). |
| `HTTP 401` or `403` | The key is wrong or lacks access. Tell the user to check `FP_API_KEY` and their API plan. Do not retry in a loop. |
| Cheat-sheet rankings rate limited | Required data is missing. Tell the user to wait about 15 to 60 minutes, then call the tool again. Progress is cached, so the rerun only repeats unfinished calls. Do not loop. |
| `FP_LEAGUE_KEY missing`, or an HTTP error on the league feed | The league key is missing or stale. Go to [league-capture.md](league-capture.md). |
| `grade_week`: no points yet, or `FP_API_KEY` not set | Optional. Skip the grade, and mention it in one line. |

The website login in `.env` (`FANTASYPROS_USERNAME` / `FANTASYPROS_PASSWORD`) is used **only** by `set_web_session` with `login`. The API source does not use it. Never read those values into chat or logs.
