# Yahoo Fantasy app map (Android, Pixel 8 Pro)

Mapped read-only on Sunday, 2026-11-08, Week 9, league "SILVER LEAGUE". Team: "Emo Rage Nerd Core". Labels are from `yf.py screen`. Coordinates are for a 1344x2992 screen and can differ on another phone.

## Timing caveats (user-reported, Sunday)

- **Waiver claims do not process on Sunday.** Claim buttons may appear and can be tapped, but the claim is not processed. Do not treat a claim as done. Verify on the Transactions page.
- **Trades cannot happen on Sunday.**
- **Team tab is locked while the user's players have already played this week.** Moves are disabled. Re-check after the week's games finish and the next lineup opens.

## Bottom navigation (app bar, present on most screens)

| Label | Notes |
|---|---|
| Home | Feed of polls, news, and promos. Not part of roster work |
| Games | Not mapped |
| News | Not mapped |
| Scores | Not mapped |

## Top tabs (y ≈ 321)

| Tab | Label | x |
|---|---|---|
| Team | `Team` | 103 |
| Matchup | `Matchup` | 298 |
| Players | `Players` | 508 |
| League | `League` | 705 |

Other top-bar labels: `Go to chat, 0 unread messages` (chat icon, x 1130–1257), `Share matchup` / `Share team roster` (share icon, x 1257).

## Team tab

- Header: team name and record (`6 - 2 - 0`, `2nd of 8`).
- Week selector: `Previous Week 9`, `Week 9`, `Next Week 9`. Past weeks can be viewed.
- Totals: `This Week (total)`, `Combined`, `Proj 127.60`.
- `Start Active Players`: a button, not mapped.
- Lineup slots, in order: `QB slot`, `RB slot` ×2, `WR slot` ×3, `TE slot`, `W/R/T slot` ×2, `K slot`, `DEF slot`, then `BN slot` (bench). A section header `Bench` sits at y ≈ 2676.
- Each player row shows name, position, opponent, projected points, and the current-week score.
- Tapping a player name opens the **player card** (see below).
- Starter-to-bench moves: **not mapped.** The current locked state blocks them.

### Player card (opened from Team or Players)

- Header: `IN YOUR RB SLOT` (or current slot), `Close` (x 1247, y 228), name in large text.
- Stats row: `Fan Pts`, `Pos Rank`, `Start (+5%)`, `Roster (0.0%)`, `League availability`.
- Tabs: `Overview`, `Game Log`, `Stats`.
- Week matchup block with the game status and projection.
- Game log lines: `WK n @ OPP, Proj x, Final y`.
- News cards and `Discuss, N Comments`.
- `Compare` (bottom, x 626).
- `Add player to watch list` (x 293, y 383). Harmless, but it is not a roster action.
- **The card has no visible Start or Bench control.** The `Start (+5%)` label is a stat, not a button. Do not assume it is a toggle.
- `Close` returns to the list you came from.

## Matchup tab

- Opponent: `Football Et al.`, `El Cuñado` (the user's team is listed on the left with score `127.60`, the opponent with `110.98`).
- Win probability: `19%` / `81%`.
- Projected totals: `127.60` vs `140.14`.
- `Week 9` selector and `All Matchups` (x 393, y 988).
- Starting lineup rows for both teams, with the same slot labels as Team.

## Players tab

- Default view (when opened): free agents list.
- `Trending` section (top of list) with players and `+x.x%` add counts. Each row has a `Claim` button (x 128, 573, 997; y 663). **`Claim` is the add action.** Do not tap it unless the user has confirmed the exact add and the drop.
- Each row: name, position, team, `Rost NN%` (ownership), and a preview of projected points.
- Filters, sort, and position tabs are below the first screen and not fully mapped.
- A quick check showed the ads banner (`INSTALL`, `optout.html`). Ignore it.

## League tab

Top: `SILVER LEAGUE` (league name), `Settings` (x 717, y 626), `privacy` link.

Menu (y 792–883):
- `Announcements`
- `Playoffs`
- `Transactions` (x 856, y 792)
- `Team Levels`
- `Commish Notes`
- `Matchups`
- `Draft` (x 825, y 883)
- `Record Book`

Standings (y 1057 and below): `Standings`, `View All`, columns `Rank`, `Team`, `W-L-T`, `PF`.

### Transactions page (read-only history, mapped)

- Title `Transactions`, back control `Navigate up` (x 71, y 222).
- Filter `ADD/DROP` at the start of each entry.
- Each entry: timestamp, player name, position, `(FA)` (free agent add) or `(W)` (waiver claim), and team name.
- Use it to verify a completed move.

### Not mapped

- `Settings`: the tap from the League page did not land on it (see the Home feed note below). Do not tap inside Settings without confirming it. It may contain options such as leaving the league.
- `Draft`: the menu item exists but the tap was not confirmed.
- `Announcements`, `Playoffs`, `Team Levels`, `Commish Notes`, `Matchups`, `Record Book`, full `Standings`: not opened.

## Known issues with the helper

- `package=?` is printed because the uiautomator root node in this app has no `package` attribute. Harmless.
- `yf.py key back` on a top-level tab can leave the app and show the launcher. Run `yf.py launch` to return.
- `tap Settings` on the League page can land on the Home feed. The tap matched nothing and did nothing, so `screen` afterwards shows where you are.
