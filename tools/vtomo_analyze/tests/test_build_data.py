import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL_DIR = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(TOOL_DIR))
import build_data


class BuildDataTest(unittest.TestCase):
    def test_build_filters_current_subscriptions_and_merges_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subs = root / "subs"
            intel = root / "intel"
            out = root / "out"
            subs.mkdir()
            intel.mkdir()
            out.mkdir()
            snapshot = {
                "account": "@yoizakura_t",
                "count": 2,
                "channels": [
                    {"channel_id": "A", "title": "Alpha", "handle": "@a"},
                    {"channel_id": "B", "title": "Beta", "handle": "@b"},
                ],
            }
            (subs / "subs_yoizakura_t_2026-09-27.json").write_text(json.dumps(snapshot), encoding="utf-8")
            rows = [
                {"ts": "2", "channel_id": "A", "channel": "Alpha", "video_id": "v1", "title": "one", "sec": 60, "views": 20, "published": "2026-09-27T00:00:00Z"},
                {"ts": "1", "channel_id": "A", "channel": "Alpha", "video_id": "v1", "title": "one", "sec": 60, "views": 10, "published": "2026-09-27T00:00:00Z"},
                {"ts": "1", "channel_id": "X", "channel": "Outside", "video_id": "vx", "title": "outside", "sec": 10, "views": 999, "published": "2026-09-27T00:00:00Z"},
            ]
            (intel / "subs_shorts_2026-09-27.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            own = {"channel": {"channel_id": "OWN"}, "api_calls": {"estimated_quota_units": 3}, "videos": [{"video_id": "ov1", "title": "own", "published_at": "2026-09-27T00:00:00Z", "views": 5}]}
            (out / "own_videos_2026-09-27.json").write_text(json.dumps(own), encoding="utf-8")
            checkpoints = root / "own_48h.jsonl"
            checkpoints.write_text(json.dumps({"video_id": "ov1", "checkpoint_h": 1, "age_h": 1.07, "views": 4, "fetched_jst": "2026-09-27T10:00:00+09:00"}) + "\n", encoding="utf-8")

            env = {
                "VTOMO_SUBS_DIR": str(subs),
                "VTOMO_CONSULT_INTEL_DIR": str(intel),
                "VTOMO_CHECKPOINTS_PATH": str(checkpoints),
                "VTOMO_OUT_DIR": str(out),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(build_data, "CONSULT_INTEL_DIR", str(intel)), mock.patch.object(build_data, "CHECKPOINTS_PATH", str(checkpoints)):
                    payload, data_path = build_data.build()

            self.assertEqual(payload["counts"], {"own_videos": 1, "subscription_channels": 2, "subscription_videos": 1})
            self.assertEqual(payload["subscriptions"]["videos"][0]["views"], 20)
            self.assertTrue(payload["own"]["videos"][0]["checkpoints"][0]["delayed"])
            self.assertTrue(Path(data_path).is_file())


if __name__ == "__main__":
    unittest.main()
