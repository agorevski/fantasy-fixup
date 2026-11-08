# Caveats to state with results

State the caveats that apply to the run being reported.

- **Cheat-sheet coverage is limited.** The rankings on the current free tier list only a few players per position (for example, about 5 QBs, 4 Ks, 4 DSTs, and 10 FLEX). A player marked `unranked` or `not on cheat sheet` is outside that list. This does not mean the player is bad. Say so when recommending moves from these lists.
- **Expert selection is an approximation.** The public API gives one accuracy score per expert per position. The advisor takes the top N by that score. It does not use the website's named accuracy groups, so the expert set can differ from the site's own lists.
- **ROS is thin.** The QB and FLEX ROS groups have only about 2 experts on the current site. Say so, and weight those results accordingly.
- **Starting slots are not read from the league.** FLEX starters are counted from the user's current lineup. The output does not check whether the league's slot counts allow a swap.
- **Week-over-week needs a prior snapshot.** The first run of a period is only a baseline.
- **Rate limits.** The free API key has limits. The advisor paces calls, retries 429s briefly, caches responses, and stops cleanly if the required rankings stay rate limited. Progress is cached, so rerunning later is cheap.
- **Web source differences.** The website's injury table lists only the status and the injury, with no practice reports or comments. The DNP check is therefore not available on the web source, and an injury entry without a practice note is not the same as a healthy player. Say so in the report. The website's expert set comes from its named accuracy lists ("Top 10 QB", "Top 20 Overall"). The site can drop experts from a list when they have no ECR for the week, and the Data status line names them.
- **Matchup data is weekly.** It reflects the current week. Run `run_weekly` again each week.
