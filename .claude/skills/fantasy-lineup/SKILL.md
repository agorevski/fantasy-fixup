---
name: fantasy-lineup
description: Weekly FantasyPros-based lineup, start/sit, waiver add, and drop analysis for the Yahoo league synced to FantasyPros, with bye, injury, per-expert pick, and week-over-week FLEX checks plus news-backed player notes. Read-only; it recommends moves and never changes the roster. Use when the user asks for weekly or rest-of-season lineup, waiver, or drop suggestions.
---

# fantasy-lineup

Produces weekly (`weekly`) or rest-of-season (`ros`) suggestions for QB, RB/WR/TE (FLEX), K, and DST.

**The user's priority is winning each WEEK.** `weekly` is the main product. `ros` is secondary and only run when asked.

Ranking sources, from the site's own accuracy groups:
- **weekly**: QB, K, DST use the Top 10 in-season accuracy experts for that position. FLEX uses the Top 20 overall.
- **ros**: QB, K, DST use the Top 20 in-season accuracy experts for that position (ROS pages). FLEX uses the Top 20 overall.

Run every command from the repo root, `~/GIT/FantasyProsFixer`, using `.venv/bin/python`.

## Pick rules (weekly)

1. **Byes.** A player on a bye this week cannot score. Never start one if a healthy option exists. The output marks them `BYE THIS WEEK`. QB, K, and DST "best picks" already skip teams on a bye. FLEX candidates on a bye are also excluded from the week-over-week check.
2. **Injuries.** Use the `INJURY:` tag and the Step 6 reporting:
   - **Out, IR, Doubtful, or no practice**: do not start. Bench, or move them if a healthy option exists.
   - **Questionable**: start only if there is no better healthy option and the reporting is neutral or positive. Say so in the table.
   - **Probable, or Limited then Full**: no penalty.
   - The injury check covers the roster and the top free agents at each position. For anyone else, check with WebSearch before recommending them.
3. **Individual experts.** Each player's `expert median` and `expert_picks` list show how each of the 20 (FLEX) or 10 (QB/K/DST) accuracy experts ranked them. Use it as a tiebreaker or as a check:
   - When two players are close in consensus rank, prefer the one more experts rank higher.
   - When the consensus and the expert median disagree, or one expert is far from the rest, name that expert and explain the gap.
   - Experts' written commentary is not in the feed, so for commentary use WebSearch.
4. **FLEX (RB/WR/TE) must improve on last week.** Each week's FLEX picks have to be consistently better than the prior week's. `fp_advisor.py` saves a snapshot of every weekly run in `.fp_cache/history/`. On the next run it pairs this week's best healthy, non-bye FLEX lineup with last week's actual FLEX starters, best to worst, ranked at **this week's** ranks. Each slot is marked `IMPROVED` or `NO IMPROVEMENT`. Do not recommend a FLEX move that is `NO IMPROVEMENT`. If a slot shows no improvement, say so and hold that starter, unless the prior player is `[no longer available]`, in which case say that instead.
5. **QB, K, and DST are exempt from the week-over-week rule.** Start the best-ranked healthy, non-bye player at each, which is the "Weekly best pick" line in the output. Do not hold a QB, K, or DST just because last week's pick was better.
6. The first run in a new period has no prior snapshot. It saves the baseline and prints `no prior snapshot yet`. Say that the week-over-week check starts next period.

## Step 1: Check the environment

1. If `.venv/bin/python` is missing, tell the user and create it with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
2. Check whether mitmproxy is installed with `.venv/bin/mitmdump --version`.
   - **If it is missing, say so and ask before installing.** Once the user agrees, run `.venv/bin/pip install mitmproxy`. This installs into the project venv only.

## Step 2: Use saved settings if they exist

`fp_advisor.py` reads `FP_LEAGUE_KEY` and `FP_TEAM_ID` from `.env`. **Never print or echo their values.**

Run the analysis directly, `.venv/bin/python fp_advisor.py weekly` (or `ros`).
- If it prints the rankings and roster, the saved settings still work. Skip to Step 5. This is the fast weekly path.
- If it fails with `FP_LEAGUE_KEY missing` or an HTTP error on the league call, the key is missing or stale. Go to Step 3.
- If it fails with an HTTP 403 on a `fantasypros.com` page, the site is blocking HTML requests. Do not retry in a loop, and do not try to get around the block. The script falls back to the cached expert list when it has one. If there is no cache, tell the user to wait and retry later.

The FantasyPros login password in `.env` (`FANTASYPROS_USERNAME` / `FANTASYPROS_PASSWORD`) is **not used**. The API calls work without a login, and automated login is blocked by a Turnstile check. Do not read those values, and do not try to log in with them. If the user wants them removed, that's their call.

## Step 3: Capture the league (only when Step 2 needs it)

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

If the proxy shows `Client TLS handshake failed ... does not trust the proxy's certificate`, the certificate trust in step 2 is not set. Ask the user to re-check it.

## Step 4: Pick the team

1. List the league's teams: `.venv/bin/python fp_advisor.py discover`. This prints the league name and each team's ID and name. It does not print the key.
2. Ask the user which team is theirs with AskUserQuestion, using the team names. Do not guess.
3. Save the choice: `.venv/bin/python fp_advisor.py discover --team-id <id>`. This writes `FP_LEAGUE_KEY` and `FP_TEAM_ID` to `.env`, with mode 600.

## Step 5: Run the analysis

1. Run `.venv/bin/python fp_advisor.py weekly` (and `ros` only if asked). The result is saved to `.fp_cache/<kind>.json`, and each weekly run is also saved as a snapshot in `.fp_cache/history/weekly-<period>.json`.
2. The period is the NFL week the FantasyPros feed reports, for example `week09`. The script reads this from the feed, so no setup is needed. `FP_WEEK` in `.env` overrides it.
3. Snapshots record the lineup as it stood when the command ran. Run `weekly` after the user has set their lineup for the week, so the next week's comparison is against the lineup they actually played.
4. Read the output and the cache. Each roster and top free-agent row has:
   - `bye`: the bye week, or `BYE THIS WEEK`
   - `injury`: a status line and any injury-table rows, when the page lists one. If this is missing, the check did not run or the page was unavailable. It does not mean the player is healthy.
   - `expert_median` and `expert_picks`: each expert's rank for the player
   - `url`: the player's FantasyPros page

## Step 6: Research every recommended player

The rankings do not include news. For **every player you will recommend starting, benching, adding, or dropping**, use WebSearch to find current reporting:
- injury designation and practice status (Limited, Full, DNP) from the team beat writer or the NFL injury report
- role changes: snap share, target share, carries, depth-chart moves, or a QB change
- matchup notes, such as the opposing defense, weather, or game script
- weekly player descriptions and expert commentary, which are not in the feed
- the date of each source

Prefer team beat reporters, the NFL injury report, and established fantasy news. If nothing recent turns up, write `no recent reporting found`. Do not invent reporting.

## Step 7: Write the report

Use markdown tables. Give the user the full lineup, the position by position decision, and the reasons behind each move.

**Lineup table** (one row per roster player, grouped by position, starters first):

| Position | Slot | Player (team) | Weekly rank | Bye / injury | Expert median | Action | Why (reporting) |
|---|---|---|---|---|---|---|---|

- Cover QB, RB/WR/TE (FLEX), K, and DST. Include every bench player.
- **Action** is one of: `Start`, `Sit (bench)`, `Start over <name>`, `Add <name> / Drop <name>`, or `Hold`.
- For QB, K, and DST, the action is the best-ranked healthy, non-bye player at that position.
- Write `unchecked` in the injury column when the lookup did not run for that player.

**Week-over-week FLEX table**:

| Slot | This week's pick | Rank now | Last week's starter | Rank now | Result |
|---|---|---|---|---|---|

Use `IMPROVED` or `NO IMPROVEMENT` for the result. Mark any player marked `[no longer available]`.

**Moves table** (only moves that pass the rules above):

| Add | Drop | Position | Rank change | Expert split | Week-over-week | Reporting |
|---|---|---|---|---|---|---|

**Player notes**: for each player you recommend moving, give one or two sentences on why, drawn from the Step 6 reporting and the expert picks. Name the source and date. Say when the reporting is thin.

Do not make roster changes. Tell the user which moves to make in Yahoo.

## Caveats to state with the results

- **FantasyPros HTML may return 403.** The script caches the expert list from earlier good reads. When the injury lookup fails, the output says so, and the injury column is marked `unchecked`.
- **ROS is thin.** The QB and FLEX ROS accuracy groups have only about 2 experts on the current site. Say so, and weight those results accordingly.
- **Starting slots are not read from the league.** FLEX starters are counted from the user's current lineup. The output does not check whether the league's slot counts allow a swap.
- **Week-over-week needs a prior snapshot.** The first run of a period is only a baseline.
- The matchup data reflects the current week. Run `weekly` again each week.
