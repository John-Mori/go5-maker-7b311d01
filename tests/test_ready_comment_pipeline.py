#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ready_libraryの同期state→vision→配信ガードを実データ形のfixtureで検証する。"""
import importlib.util
import json
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_module(name, rel):
    path = os.path.join(ROOT, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CAND = load_module("go5_candidates_json_test", os.path.join(
    "docs", "departments", "product-scout", "tools", "candidates_json.py"))
VISION = load_module("go5_vision_comments_test", os.path.join(
    "scripts", "teian", "vision_comments.py"))
PUBLISH = load_module("go5_publish_candidates_test", os.path.join(
    "scripts", "teian", "publish_candidates.py"))

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64


class ReadyCommentPipelineTest(unittest.TestCase):
    def test_sync_state_extracts_manifest_and_old_idb_without_resurrection(self):
        state = {
            "fmt": 2,
            "ls": {
                "cand_items": {"t": 10, "v": json.dumps([
                    {"cid": "d_ready", "title": "投稿画像あり", "addedAt": 20},
                    {"cid": "d_deleted", "title": "削除済み", "addedAt": 20},
                ], ensure_ascii=False)},
                "go5_image_manifest_v1": {"t": 30, "v": json.dumps({
                    "ref:d_ready": {"keys": [H1], "prev": 0, "at": 30},
                    "ref:d_deleted": {"keys": [], "prev": 0, "at": 30},
                })},
                "unrelated_secret": {"t": 1, "v": "must-not-leak"},
            },
            "idb": {
                "ref:d_old": {"t": 5, "v": {"imgs": [{"__img": H2}]}},
                "ref:d_deleted": {"t": 5, "v": {"imgs": [{"__img": H3}]}},
            },
        }
        got = CAND.parse_ready_sync_bundle(json.dumps({"blob": json.dumps(state)}), "https://sync.example/img/")
        self.assertEqual(set(got), {"d_ready", "d_old"})
        self.assertEqual(got["d_ready"]["vision_images"], ["https://sync.example/img/" + H1])
        self.assertEqual(got["d_ready"]["item"]["title"], "投稿画像あり")
        self.assertNotIn("d_deleted", got, "manifest keys:[] must beat a stale IDB image ref")
        self.assertNotIn("unrelated_secret", json.dumps(got))

    def test_ready_builder_and_vision_are_fill_empty_only(self):
        sync = {
            "d_ready": {"vision_images": ["https://sync.example/img/" + H1],
                        "item": {"title": "端末タイトル", "price": 330}},
            "d_excluded": {"vision_images": ["https://sync.example/img/" + H2], "item": {}},
        }
        info = {
            "prices": {"price": 110, "list_price": 550},
            "sampleImageURL": {"sample_l": {"image": ["https://example.test/sample.jpg"]}},
        }
        ready = CAND.build_ready_library(
            sync,
            {"d_ready": {"cid": "d_ready", "title": "D1タイトル", "sales_n": 100,
                         "info_json": json.dumps(info)}},
            {"d_excluded"}, set(), {}, {}, {"acc1": set(), "acc2": set()},
        )
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["title"], "D1タイトル")
        self.assertEqual(ready[0]["vision_images"], ["https://sync.example/img/" + H1])
        self.assertEqual(ready[0]["images"], ["https://example.test/sample.jpg"])
        self.assertEqual(ready[0]["comments"], [])

        existing = [{"n": 1, "text": "既存案"}, {"n": 2, "text": "既存案2"}, {"n": 3, "text": "既存案3"}]
        doc = {
            "candidates": [{"cid": "d_pool", "comments": existing, "images": ["pool.jpg"]}],
            "ready_library": [ready[0]],
        }
        targets = VISION.comment_targets(doc)
        self.assertEqual([c["cid"] for c in targets], ["d_pool", "d_ready"])
        self.assertIs(targets[0]["comments"], existing)

        out = os.path.join(ROOT, "tests", ".ready-pipeline-out.json")
        store_path = os.path.join(ROOT, "tests", ".ready-pipeline-content-store.json")
        try:
            with open(store_path, "w", encoding="utf-8") as f:
                json.dump({"d_pool": {"comments": existing}}, f, ensure_ascii=False)
            generated = [{"n": 1, "text": "新規1"}, {"n": 2, "text": "新規2"}, {"n": 3, "text": "新規3"}]
            ready[0]["comments"] = generated
            VISION.persist_content_store(out, targets, store_path=store_path)
            with open(store_path, encoding="utf-8") as f:
                store = json.load(f)
            self.assertEqual(store["d_pool"]["comments"], existing)
            self.assertEqual(store["d_ready"]["comments"], generated)
        finally:
            for path in (out, store_path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def test_publish_guard_requires_ready_comments_but_not_room_comments(self):
        room = {"mitoma": "ok", "main": {"text": "ok"}}
        path = os.path.join(ROOT, "tests", ".ready-pipeline-publish.json")
        try:
            doc = {
                "candidates": [{"cid": "d_pool", "comments": [{"text": "ok"}], "room_comments": room}],
                "ready_library": [{"cid": "d_ready", "comments": []}],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            self.assertEqual(PUBLISH.guard_not_empty(path), ["ready:d_ready(④comments)"])
            doc["ready_library"][0]["comments"] = [{"text": "ok"}]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            self.assertEqual(PUBLISH.guard_not_empty(path), [])
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
