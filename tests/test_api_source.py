"""Public-API source: ranking-type fallback and the waiver-wire warning (no network)."""

import unittest
from unittest import mock

from fantasy_lineup import advisor


def ranking(type_name):
    return {"ranking_type_name": type_name, "experts_available": {"included": [1, 2, 3, 4, 5]},
            "players": [{"player_id": 1, "player_name": "A", "player_position_id": "QB", "rank_ecr": 1,
                         "r2p_pts": "20.5", "rank_min": "1", "rank_max": "3"}]}


class ApiConsensusTests(unittest.TestCase):
    def setUp(self):
        advisor._api_type.clear()

    def test_weekly_type_falls_back_and_warns(self):
        calls = []

        def fake(path, params, ttl=None, retries=None):
            calls.append(params["type"])
            if params["type"] == "WEEKLY":
                raise advisor.ApiHttpError("bad type", 400)
            return ranking("Waiver Wire")

        with mock.patch.object(advisor, "api_get", side_effect=fake):
            players, info = advisor.consensus("weekly", "QB", [1, 2, 3, 4, 5], 9)
        self.assertEqual(calls, ["WEEKLY", "WW"])
        self.assertEqual(players[1]["proj"], 20.5)
        self.assertEqual(info["experts"], 5)
        self.assertTrue(any("waiver-wire" in w for w in info["warnings"]))

    def test_weekly_type_accepted(self):
        with mock.patch.object(advisor, "api_get", return_value=ranking("Week 9 Rankings")) as m:
            _, info = advisor.consensus("weekly", "QB", [1], 9)
            advisor.consensus("weekly", "K", [1], 9)
        self.assertEqual([c.args[1]["type"] for c in m.call_args_list], ["WEEKLY", "WEEKLY"])
        self.assertFalse(any("waiver-wire" in w for w in info["warnings"]))

    def test_other_errors_propagate(self):
        with mock.patch.object(advisor, "api_get", side_effect=advisor.ApiHttpError("nope", 403)):
            with self.assertRaises(advisor.ApiHttpError):
                advisor.consensus("weekly", "QB", [1], 9)

    def test_scoring(self):
        self.assertEqual(advisor.normalize_scoring("STD"), "STD")
        self.assertEqual(advisor.normalize_scoring("HALF_PPR"), "HALF")
        self.assertEqual(advisor.normalize_scoring("PPR"), "PPR")


if __name__ == "__main__":
    unittest.main()
