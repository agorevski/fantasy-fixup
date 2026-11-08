# Caveats to state with results

State the caveats that apply to the run being reported.

- **Projections are FantasyPros' and approximate.** Rankings set the lineup; projected points size the gaps. A gap under 1.5 points is a close call, not a clear edge.
- **The stance is only as good as the win probability.** It comes from FantasyPros' matchup feed. It changes during the week and once games start.
- **Expert selection is an approximation.** Weekly lists use the top experts by accuracy: the site's named lists ("Top 10 QB", "Top 20 Overall") on the web source, or the API's `accuracy_weekly` score. The site can drop experts with no ranks for the week; Data status names them.
- **ROS uses the full consensus.** It is not filtered by accuracy. Give the expert count from the "Experts per consensus" line.
- **API source rankings.** If Data status says the API served waiver-wire rankings, rostered players show as unranked and the lineup is not reliable on that source. Use the web source.
- **Web source without `FP_API_KEY`.** The injury table has the status and the injury only, with no practice reports, so the DNP check does not run. An injury entry without a practice note is not the same as a healthy player. Role evidence is also unavailable, so moves stay provisional.
- **Locks.** Players whose games have started are marked `LOCKED`. A run late in the week only changes the players who have not played yet.
- **Rate limits.** The free API key has limits. After a 429 that does not clear, optional API lookups are skipped for 10 minutes rather than waited on. Rankings are cached for 6 hours, so a rerun is cheap.
- **Grades use the snapshot's lineup.** Lineup edits made after the last `run_weekly` of that week are not seen.
- **Week-over-week trend needs a prior snapshot.** The first run is only a baseline.
