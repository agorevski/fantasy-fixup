"""grade_week: scores actual, recommended, and hindsight lineups with mocked FantasyPros points."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fantasy_lineup import advisor, grade

SLOTS = ["QB", "RB", "WR", "TE", "WR/RB/TE"]


def p(fid, name, pos, slot):
    return {"fpId": fid, "name": name, "pos": pos, "slot": slot}


class GradeTests(unittest.TestCase):
    def test_grade_week(self):
        roster = [p(1, "QB", "QB", "starter"), p(2, "RB", "RB", "starter"), p(3, "WR", "WR", "starter"),
                  p(4, "TE", "TE", "starter"), p(5, "Flex", "WR", "starter"), p(6, "Bench WR", "WR", "bench")]
        snap = {"week": 9, "period": "week09", "scoring": "STD", "slots": SLOTS, "roster": roster,
                "lineup": {"recommended": [{"fpId": i} for i in (1, 2, 3, 4, 6)]},
                "moves": {"recommended": [{"add": "Add", "add_id": 7, "drop": "Drop", "drop_id": 8}]}}
        points = {1: {9: 20.0}, 2: {9: 10.0}, 3: {9: 8.0}, 4: {9: 5.0}, 5: {9: 2.0}, 6: {9: 15.0},
                  7: {9: 9.0}, 8: {9: 1.0}}
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp)
            (hist / "weekly-week09.json").write_text(json.dumps(snap))
            with mock.patch.object(advisor, "history_dir", return_value=hist), \
                    mock.patch.object(advisor, "player_points", return_value=points):
                text = grade.grade_week(9, "web")
                log = json.loads((hist / grade.LOG_NAME).read_text())
        entry = log["9"]
        self.assertEqual(entry["actual"], 45.0)
        self.assertEqual(entry["recommended"], 58.0)
        self.assertEqual(entry["hindsight"], 58.0)
        self.assertEqual(entry["advice_gain"], 13.0)
        self.assertIn("+8.0 pts that week", text)
        self.assertIn("Season log", text)


if __name__ == "__main__":
    unittest.main()
