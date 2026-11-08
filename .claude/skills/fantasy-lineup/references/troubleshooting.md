# Running the analysis: error handling (Step 2)

Run `run_weekly` or `run_ros` only after [configuration.md](configuration.md) is confirmed.

If the tool returns the report, go to the report steps in [report-format.md](report-format.md).

| Result | Action |
|---|---|
| A `Data status` section listing missing optional data | **Not an error.** Use what is there, and say what is missing. |
| `ERROR` with `FP_API_KEY missing` | Go back to Step 0 in [configuration.md](configuration.md). |
| `HTTP 401` or `403` | The key is wrong or lacks access. Tell the user to check `FP_API_KEY` and their API plan. Do not retry in a loop. |
| Cheat-sheet rankings rate limited | Required data is missing. Tell the user to wait about 15 to 60 minutes, then call the tool again. Progress is cached, so the rerun only repeats unfinished calls. Do not loop. |
| `FP_LEAGUE_KEY missing`, or an HTTP error on the league feed | The league key is missing or stale. Go to [league-capture.md](league-capture.md). |

The website login in `.env` (`FANTASYPROS_USERNAME` / `FANTASYPROS_PASSWORD`) is used **only** by `set_web_session` with `login`. The API source does not use it. Never read those values into chat or logs.
