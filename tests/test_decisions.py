"""Unit tests for lineup legality and the decision gates. Run: PYTHONPATH=src python -m unittest discover tests"""

import unittest

from fantasy_lineup import decisions
from fantasy_lineup.lineup import best_lineup, fillable, parse_slots, unfilled

SLOTS = parse_slots("QB,RB,RB,WR,WR,WR,TE,WR/RB/TE,WR/RB/TE,DST,K,BN,BN,BN,BN,BN,BN")


def player(fid, name, pos, rank, slot="bench", lineup_slot=None, **kw):
    grp = "FLX" if pos in ("RB", "WR", "TE") else pos
    p = {"fpId": fid, "name": name, "pos": pos, "group": grp, "rank": rank, "slot": slot,
         "lineup_slot": lineup_slot or ("BN" if slot == "bench" else pos), "injury": [], "bye_now": False,
         "locked": False, "proj": None}
    p.update(kw)
    return p


def week9_roster():
    """The week 9 web-source roster: Pitts starts at TE and RBs/WRs on the bench outrank him."""
    return [
        player(1, "Dak Prescott", "QB", 4, "starter", ros_rank=9),
        player(2, "Christian McCaffrey", "RB", 3, "starter", ros_rank=6),
        player(3, "Quinshon Judkins", "RB", 27, "starter", ros_rank=37),
        player(4, "CeeDee Lamb", "WR", 13, "starter", ros_rank=17),
        player(5, "Amon-Ra St. Brown", "WR", 15, "starter", ros_rank=16),
        player(6, "Tee Higgins", "WR", 21, "starter", ros_rank=26),
        player(7, "Kyle Pitts Sr.", "TE", 89, "starter", ros_rank=139),
        player(8, "Malik Nabers", "WR", 31, "starter", "WR/RB/TE", ros_rank=22),
        player(9, "Ashton Jeanty", "RB", 34, "starter", "WR/RB/TE", ros_rank=18),
        player(10, "Evan McPherson", "K", 2, "starter", ros_rank=4),
        player(11, "Houston Texans", "DST", 2, "starter", ros_rank=3),
        player(12, "Patrick Mahomes II", "QB", 8, ros_rank=7),
        player(13, "Braelon Allen", "RB", 55, ros_rank=104),
        player(14, "Kyle Monangai", "RB", 287, ros_rank=89),
        player(15, "Ladd McConkey", "WR", 68, ros_rank=61),
        player(16, "Rome Odunze", "WR", 63, ros_rank=69),
        player(17, "Dalton Kincaid", "TE", 93, ros_rank=103),
    ]


class LineupTests(unittest.TestCase):
    def test_parse_slots_drops_bench(self):
        self.assertEqual(len(SLOTS), 11)
        self.assertNotIn("BN", SLOTS)

    def test_te_slot_never_filled_by_rb_or_wr(self):
        # Week 9 bug: 'START Braelon Allen over Kyle Pitts' would leave the TE slot illegal
        plan = decisions.plan_lineup(week9_roster(), SLOTS, None)
        te = [s for s in plan["recommended"] if s["slot"] == "TE"]
        self.assertEqual([s["name"] for s in te], ["Kyle Pitts Sr."])
        self.assertFalse(any(c["start"] in ("Braelon Allen", "Ladd McConkey", "Rome Odunze")
                             for c in plan["changes"]))

    def test_bye_starter_is_replaced(self):
        rows = week9_roster()
        rows[6]["bye_now"] = True  # Pitts on bye
        plan = decisions.plan_lineup(rows, SLOTS, None)
        te = next(s for s in plan["recommended"] if s["slot"] == "TE")
        self.assertEqual(te["name"], "Dalton Kincaid")

    def test_locked_starter_stays_and_locked_bench_cannot_start(self):
        rows = week9_roster()
        rows[2]["locked"] = True            # Judkins (starter) game started: stays
        rows[12].update(rank=1)             # Braelon Allen now ranked #1 ...
        rows[12]["locked"] = True           # ... but his game started on the bench
        plan = decisions.plan_lineup(rows, SLOTS, None)
        names = {s["name"] for s in plan["recommended"]}
        self.assertIn("Quinshon Judkins", names)
        self.assertNotIn("Braelon Allen", names)

    def test_empty_slot_reported(self):
        rows = [p for p in week9_roster() if p["pos"] != "K"]
        plan = decisions.plan_lineup(rows, SLOTS, None)
        self.assertEqual(plan["empty_slots"], ["K"])

    def test_optimal_uses_flex_correctly(self):
        rows = [player(1, "QB1", "QB", 1), player(2, "K1", "K", 1), player(3, "D1", "DST", 1),
                player(4, "TE1", "TE", 5), player(5, "TE2", "TE", 6),
                player(6, "RB1", "RB", 1), player(7, "RB2", "RB", 2),
                player(8, "WR1", "WR", 3), player(9, "WR2", "WR", 4), player(10, "WR3", "WR", 50),
                player(11, "RB3", "RB", 60)]
        lineup = best_lineup(rows, SLOTS, decisions.weekly_key)
        names = {p["name"] for p in lineup.values()}
        # TE2 (#6) should take a FLEX over WR3/RB3, and every slot is legal
        self.assertIn("TE2", names)
        self.assertEqual(len(lineup), 11)

    def test_fillable(self):
        rows = week9_roster()
        no_te = [p for p in rows if p["pos"] != "TE"]
        self.assertTrue(fillable(rows, SLOTS))
        self.assertFalse(fillable(no_te, SLOTS))
        self.assertEqual(unfilled(no_te, SLOTS), ["TE"])


class CloseCallTests(unittest.TestCase):
    def test_underdog_prefers_ceiling(self):
        a = player(1, "Floor", "WR", 30, proj=10.0, rank_min=20, rank_max=35)
        b = player(2, "Ceiling", "WR", 31, proj=9.5, rank_min=8, rank_max=60)
        self.assertEqual(decisions.prefer(a, b, "underdog")[0]["name"], "Ceiling")
        self.assertEqual(decisions.prefer(a, b, "favorite")[0]["name"], "Floor")

    def test_healthy_beats_questionable(self):
        a = player(1, "Q", "WR", 30, proj=10.0, injury=["Questionable | Ankle"])
        b = player(2, "H", "WR", 31, proj=9.6)
        self.assertEqual(decisions.prefer(a, b, "neutral")[0]["name"], "H")

    def test_posture(self):
        self.assertEqual(decisions.posture(0.25), "underdog")
        self.assertEqual(decisions.posture(0.75), "favorite")
        self.assertEqual(decisions.posture(0.5), "neutral")


class MoveTests(unittest.TestCase):
    COV = {g: {"weekly": 16, "ros": 40} for g in ("QB", "K", "DST", "FLX")}

    def run_moves(self, rows, fas, **kw):
        return decisions.propose_moves(rows, fas, SLOTS, weekly=True, coverage=kw.get("coverage", self.COV),
                                       expert_lists=kw.get("expert_lists"), evidence=kw.get("evidence"),
                                       today_ord=0, week=9)

    @staticmethod
    def only_weak(rows, names):
        """Give everyone except `names` a strong ROS rank, so only those players are drop candidates."""
        for p in rows:
            if p["name"] not in names:
                p["ros_rank"] = 10
        return rows

    def test_never_drops_both_tes(self):
        # Week 9 bug: drop Kincaid AND Pitts in the same run left no TE
        rows = self.only_weak(week9_roster(), {"Kyle Pitts Sr.", "Dalton Kincaid"})
        fas = {"FLX": [player(101, "Jadarian Price", "RB", 42, "free agent", ros_rank=75),
                       player(102, "Alvin Kamara", "RB", 58, "free agent", ros_rank=50)]}
        res = self.run_moves(rows, fas)
        drops = [m["drop"] for m in res["recommended"] + res["provisional"]]
        self.assertFalse({"Kyle Pitts Sr.", "Dalton Kincaid"} <= set(drops))
        self.assertTrue(any(h["failed"].startswith("legal") for h in res["held"]))

    def test_noise_margin_holds(self):
        rows = self.only_weak(week9_roster(), {"Ladd McConkey"})
        fas = {"FLX": [player(101, "Ryan Flournoy", "WR", 60, "free agent", ros_rank=59)]}  # vs McConkey ROS 61
        res = self.run_moves(rows, fas)
        self.assertEqual(res["recommended"] + res["provisional"], [])

    def test_thin_coverage_holds(self):
        cov = dict(self.COV, FLX={"weekly": 16, "ros": 3})
        fas = {"FLX": [player(101, "Star", "RB", 10, "free agent", ros_rank=5)]}
        res = self.run_moves(week9_roster(), fas, coverage=cov)
        self.assertEqual(res["recommended"] + res["provisional"], [])
        self.assertTrue(res["held"][0]["failed"].startswith("coverage"))

    def test_weekly_regression_holds(self):
        fas = {"FLX": [player(101, "Stash", "RB", 300, "free agent", ros_rank=5)]}
        res = self.run_moves(week9_roster(), fas)
        self.assertTrue(any(h["failed"].startswith("weekly") for h in res["held"]))

    def test_full_evidence_recommends(self):
        fas = {"FLX": [player(101, "Star", "RB", 10, "free agent", ros_rank=5, opp="vs NYJ", grade="A")]}
        lists = {e: {101: 10, 14: 200} for e in range(8)}
        ev = {101: {"points": {8: 15.0}, "news": []}, 14: {"points": {8: 2.0}, "news": []}}
        res = self.run_moves(week9_roster(), fas, expert_lists=lambda g: lists, evidence=lambda ps: ev)
        self.assertEqual([(m["add"], m["drop"]) for m in res["recommended"]], [("Star", "Kyle Monangai")])

    def test_missing_role_is_provisional(self):
        fas = {"FLX": [player(101, "Star", "RB", 10, "free agent", ros_rank=5, opp="vs NYJ")]}
        lists = {e: {101: 10, 14: 200} for e in range(8)}
        res = self.run_moves(week9_roster(), fas, expert_lists=lambda g: lists, evidence=None)
        self.assertEqual(res["recommended"], [])
        self.assertIn("role", res["provisional"][0]["missing"])

    def test_outlier_breadth(self):
        lists = {1: {1: 10, 2: 20}, 2: {1: 10, 2: 20}, 3: {1: 30, 2: 20}, 4: {1: 30, 2: 20}, 5: {1: 1, 2: 90}}
        b = decisions.breadth(lists, 1, 2)
        self.assertTrue(b["majority"])
        self.assertFalse(b["robust"])


class LookaheadTests(unittest.TestCase):
    def test_both_tes_on_bye(self):
        rows = week9_roster()
        for p in rows:
            p["bye"] = "11" if p["pos"] == "TE" else "14"
        self.assertTrue(any(line.startswith("week 11: cannot fill TE") for line in decisions.lookahead(rows, SLOTS, 9)))


if __name__ == "__main__":
    unittest.main()
