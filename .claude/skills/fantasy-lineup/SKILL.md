---
name: fantasy-lineup
description: Weekly FantasyPros-based lineup, start/sit, waiver add, and drop analysis for the Yahoo league synced to FantasyPros, with bye, injury, per-expert pick, and week-over-week FLEX checks plus news-backed player notes. Read-only; it recommends moves and never changes the roster. Use when the user asks for weekly or rest-of-season lineup, waiver, or drop suggestions.
---

# fantasy-lineup

Produces weekly (`weekly`) or rest-of-season (`ros`) suggestions for QB, RB/WR/TE (FLEX), K, and DST.

**The user's priority is winning each WEEK.** `weekly` is the main product. `ros` is secondary and only run when asked.

**Use the MCP tools, not raw Python.** The `fantasy-lineup` server (defined in `.mcp.json`, implemented in `fp_mcp_server.py`) exposes every step of this skill. Call the tools below. Do not run `fp_advisor.py` or any other Python through Bash.

| Tool | Purpose |
|---|---|
| `check_config` | Step 0: which `.env` settings are present (returns presence only, never values) |
| `run_weekly` | Step 2: weekly analysis; optional `week` override |
| `run_ros` | Step 2: rest-of-season analysis (only when asked) |
| `list_league_teams` | Step 4: league name and team IDs/names (no key returned) |
| `save_team` | Step 4: save the user's team ID after they choose it |
| `list_snapshots` | Step 5: saved weekly snapshots used by the FLEX check |

Tool names may appear with the server prefix, for example `mcp__fantasy-lineup__run_weekly`.

## Data sources and priority

Data comes from the official FantasyPros public API. The league roster comes from the FantasyPros league feed, which needs `FP_LEAGUE_KEY` and `FP_TEAM_ID`.

Data is split into two buckets, and they are used in this order:

**Bucket 1 (required): the cheat-sheet rankings and the roster.**
- Weekly: QB, K, DST, and FLEX cheat-sheet rankings, plus the bye weeks they carry. QB, K, and DST use the top 10 experts for that position. FLEX uses the top 20 overall. Experts are ranked by the API's `accuracy_weekly` score for each position.
- ROS: the same groups from the ROS rankings. QB, K, DST use the top 20 experts. FLEX uses the top 20 overall.
- The roster (starters and bench) from the league feed.

**Bucket 2 (optional, never blocking): everything else.** Individual injury reports, per-expert picks and medians, and news. Use these when they are present. If they are missing or rate limited, the analysis still proceeds on bucket 1. The report's **Data status** section says what was missing. Do not hold the final assessment for bucket 2. Do not wait for it or retry it in a loop.

Run `run_weekly` or `run_ros` only after Step 0 is confirmed.

## Pick rules (weekly)

1. **Byes.** A player on a bye this week cannot score. Never start one if a healthy option exists. The output marks them `BYE THIS WEEK`. QB, K, and DST "best picks" already skip teams on a bye. FLEX candidates on a bye are also excluded from the week-over-week check.
2. **Injuries (bucket 2).** Use the `INJURY:` tag when injury data is present. If the injury lookup failed or is missing, the injury status is `unchecked`, and that is an allowed state, not a reason to stop.
   - **Out, IR, Doubtful, or no practice**: do not start. Bench, or move them if a healthy option exists.
   - **Questionable**: start only if there is no better healthy option and the reporting is neutral or positive. Say so in the table.
   - **Probable, or Limited then Full**: no penalty.
   - Injury data covers the roster and the top free agents at each position. For anyone else, check with WebSearch only if you have time, and do not block on it.
3. **Individual experts (bucket 2).** Each player's `expert median` and `expert_picks` list show how each of the top experts ranked them. Use them as a tiebreaker or a check when present:
   - When two players are close in consensus rank, prefer the one more experts rank higher.
   - When the consensus and the expert median disagree, or one expert is far from the rest, name that expert and explain the gap.
   - Experts' written commentary is not in the feed, so for commentary use WebSearch.
4. **FLEX (RB/WR/TE) must improve on last week.** Each week's FLEX picks have to be consistently better than the prior week's. Each weekly run saves a snapshot to `.fp_cache/history/`. On the next run it pairs this week's best healthy, non-bye FLEX lineup with last week's actual FLEX starters, best to worst, ranked at **this week's** ranks. Each slot is marked `IMPROVED` or `NO IMPROVEMENT`. Do not recommend a FLEX move that is `NO IMPROVEMENT`. If a slot shows no improvement, say so and hold that starter, unless the prior player is `[no longer available]`, in which case say that instead.
5. **QB, K, and DST are exempt from the week-over-week rule.** Start the best-ranked healthy, non-bye player at each, which is the "Weekly best pick" line in the output. Do not hold a QB, K, or DST just because last week's pick was better. The "Weekly best pick" line does not check injuries. If the top pick is `OUT` in the injury data, use the next healthy player and say why.
6. The first run in a new period has no prior snapshot. It saves the baseline and prints `no prior snapshot yet`. Say that the week-over-week check starts next period.

## Step 0: Confirm configuration before anything else (always)

Do this before any tool that calls the API or the league feed, every time the skill runs. Do not skip the check itself, even when the user seems to be in a hurry.

1. Call `check_config`. It returns which of `FP_API_KEY`, `FP_LEAGUE_KEY`, `FP_TEAM_ID`, and `FP_SEASON` are present, without values.
   - If the tool itself fails, tell the user to check that the MCP server is connected (`.mcp.json`, and that `.venv` has `requirements.txt` installed).
2. **If all four settings are present, skip the confirmation prompt.** Do not ask with AskUserQuestion. Briefly list the settings as present and go straight to Step 2.
3. Otherwise, show the user the check result as a list of settings marked present or missing. Then ask with AskUserQuestion, for example: "Are your configurations set and ready? (`FP_API_KEY` in `.env` is required; `FP_LEAGUE_KEY` and `FP_TEAM_ID` are required for the roster; `FP_SEASON` defaults to 2026.)"
   - Options: `All set, continue`, `Need to fix .env first (stop here)`.
4. Do not proceed unless the user confirms. If the user confirms but a required setting is still missing, stop and say which one.
   - **`FP_API_KEY` missing:** tell the user to add `FP_API_KEY=<your key>` to `.env`. They can copy the line from `.env.example` and fill it in. Do not ask them to paste the key into chat, and do not write it anywhere except `.env`.
   - **`FP_LEAGUE_KEY` or `FP_TEAM_ID` missing:** go to Step 3.
   - **`FP_SEASON` blank or missing:** not an error. The code defaults to 2026.
4. `.env` is listed in `.gitignore`. Keep it that way. Never print, echo, or commit these values.

## Step 1: Check tools

1. Call `check_config` (Step 0). If the MCP tools are not available, stop and tell the user the `fantasy-lineup` server is not connected.
2. mitmproxy is only needed for Step 3, the one-time league capture. It is needed only when `FP_LEAGUE_KEY` or `FP_TEAM_ID` is missing.
   - **If it is missing, say so and ask before installing.** Once the user agrees, run `.venv/bin/pip install mitmproxy`. This installs into the project venv only.

## Step 2: Run the analysis

Call `run_weekly` (or `run_ros` only if asked). Run it only after Step 0 is confirmed.

- If it returns the report, go to Step 5.
- A `Data status` section listing missing optional data is **not an error**. Use what is there, and say what is missing.
- If the result says `ERROR` with `FP_API_KEY missing`, go back to Step 0.
- If it says `HTTP 401` or `403`, the key is wrong or lacks access. Tell the user to check `FP_API_KEY` and their API plan. Do not retry in a loop.
- If it says the **cheat-sheet rankings** are rate limited, the required data is missing. Tell the user to wait (about 15 to 60 minutes) and call the tool again. Progress is cached, so the rerun only repeats unfinished calls. Do not loop.
- If it says `FP_LEAGUE_KEY missing`, or an HTTP error on the league feed, the league key is missing or stale. Go to Step 3.

The FantasyPros website login in `.env` (`FANTASYPROS_USERNAME` / `FANTASYPROS_PASSWORD`), if present, is **not used**. The API needs only `FP_API_KEY`. Do not read those values, and do not try to log in with them.

## Step 3: Capture the league (only when `FP_LEAGUE_KEY` or `FP_TEAM_ID` is missing)

The public API does not expose the league roster, so the league key has to be captured from the browser once. Skip this step if Step 0 showed both values present.

Tell the user this step needs them to run commands in their own terminal and sign in themselves. The skill cannot do the sign-in.

1. Start the proxy in one terminal:
   `! cd ~/GIT/FantasyProsFixer && .venv/bin/mitmdump -s capture_addon.py -p 8081`
   The first run creates mitmproxy's CA certificate in `~/.mitmproxy/`.
2. The first time only, trust that certificate. In Keychain Access, open `~/.mitmproxy/mitmproxy-ca-cert.pem`, set it to **Always Trust**, and restart Chrome. This is a root-level trust change. Remove it again after capture, and say so.
3. Launch a separate Chrome profile through the proxy:
   `! "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --proxy-server=http://127.0.0.1:8081 --user-data-dir=/tmp/fp-chrome https://www.fantasypros.com/accounts/signin/`
4. The user signs in, opens their **league roster / My Team** page and the **matchup** page, then presses Ctrl-C in the proxy terminal.
5. Delete the session cookies the capture saved: `rm -f .fp_capture/auth.json`. The analysis doesn't need them.
6. Tell the user to stop the proxy and remove the mitmproxy certificate from Keychain.
7. Call `list_league_teams` (Step 4) to save the key.

If the proxy shows `Client TLS handshake failed ... does not trust the proxy's certificate`, the certificate trust in step 2 is not set. Ask the user to re-check it.

## Step 4: Pick the team

1. Call `list_league_teams`. It returns the league name and each team's ID and name. It does not return the key.
2. Ask the user which team is theirs with AskUserQuestion, using the team names. Do not guess.
3. Call `save_team` with the chosen team ID. This writes `FP_LEAGUE_KEY` and `FP_TEAM_ID` to `.env`, with mode 600.

## Step 5: Read the results

1. The result is saved to `.fp_cache/<kind>.json`. Each weekly run is also saved as a snapshot in `.fp_cache/history/weekly-<period>.json`. Call `list_snapshots` to see them.
2. The period is the NFL week the API reports, for example `week09`. `FP_WEEK` in `.env` overrides it.
3. Snapshots record the lineup as it stood when the analysis ran. Run `run_weekly` after the user has set their lineup for the week, so the next week's comparison is against the lineup they actually played.
4. Each roster and top free-agent row has:
   - `bye`: the bye week, or `BYE THIS WEEK` (bucket 1)
   - `injury` (bucket 2): status, injury type, practice reports, and comments from the API. An empty list means no injury is listed. It does not confirm the player is healthy. A `lookup failed` entry means the injury data was not fetched, so the status is `unchecked`.
   - `expert_median` and `expert_picks` (bucket 2): each expert's rank for the player. `experts checked X/Y` means only X of Y expert lookups finished.
   - `url`: the player's FantasyPros page

## Step 6: Research recommended players (optional, never blocking)

The rankings do not include news. Bucket 2 news is nice to have, but it is **not required** for the assessment. If time and the rate limit allow, use WebSearch for the players you recommend starting, benching, adding, or dropping:
- injury designation and practice status (Limited, Full, DNP) from the team beat writer or the NFL injury report
- role changes: snap share, target share, carries, depth-chart moves, or a QB change
- matchup notes, such as the opposing defense, weather, or game script
- weekly player descriptions and expert commentary, which are not in the feed
- the date of each source

Prefer team beat reporters, the NFL injury report, and established fantasy news. If nothing recent turns up, write `no recent reporting found`. Do not invent reporting. If the research is skipped, say so in the report.

## Step 7: Write the report

Use markdown tables. Give the user the full lineup, the position by position decision, and the reasons behind each move. Start with the **Data status** section from the tool output, so the user sees what was and was not used.

**Lineup table** (one row per roster player, grouped by position, starters first):

| Position | Slot | Player (team) | Weekly rank | Bye / injury | Expert median | Action | Why (reporting) |
|---|---|---|---|---|---|---|---|

- Cover QB, RB/WR/TE (FLEX), K, and DST. Include every bench player.
- **Action** is one of: `Start`, `Sit (bench)`, `Start over <name>`, `Add <name> / Drop <name>`, or `Hold`.
- For QB, K, and DST, the action is the best-ranked healthy, non-bye player at that position.
- Write `unchecked` in the injury column when the injury data was not fetched for that player. Write `not on cheat sheet` in the rank column for players the cheat sheet does not list.

**Week-over-week FLEX table**:

| Slot | This week's pick | Rank now | Last week's starter | Rank now | Result |
|---|---|---|---|---|---|

Use `IMPROVED` or `NO IMPROVEMENT` for the result. Mark any player marked `[no longer available]`.

**Moves table** (only moves that pass the rules above):

| Add | Drop | Position | Rank change | Expert split | Week-over-week | Reporting |
|---|---|---|---|---|---|---|

**Player notes**: for each player you recommend moving, give one or two sentences on why, drawn from the Step 6 reporting (if done) and the cheat-sheet and expert data. Name the source and date. Say when the reporting is thin or was not checked.

Do not make roster changes. Tell the user which moves to make in Yahoo.

## Caveats to state with the results

- **Cheat-sheet coverage is limited.** The rankings returned on the current free tier list only a few players per position (for example, about 5 QBs, 4 Ks, 4 DSTs, and 10 FLEX). A player marked `unranked` or `not on cheat sheet` is outside that list. It does not mean the player is bad. Say so when recommending moves from these lists.
- **Expert selection is an approximation.** The public API gives one accuracy score per expert per position. The advisor takes the top N by that score. It does not use the website's named accuracy groups, so the expert set can differ from the site's own lists.
- **ROS is thin.** The QB and FLEX ROS groups have only about 2 experts on the current site. Say so, and weight those results accordingly.
- **Starting slots are not read from the league.** FLEX starters are counted from the user's current lineup. The output does not check whether the league's slot counts allow a swap.
- **Week-over-week needs a prior snapshot.** The first run of a period is only a baseline.
- **Rate limits.** The free API key has limits. The advisor paces calls, retries 429s briefly, caches responses, and stops cleanly if the required rankings stay rate limited. Progress is cached, so rerunning later is cheap.
- The matchup data reflects the current week. Run `run_weekly` again each week.
