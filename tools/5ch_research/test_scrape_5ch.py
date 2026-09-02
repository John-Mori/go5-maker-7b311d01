# -*- coding: utf-8 -*-
"""scrape_5ch のユニットテスト。

外へ出る手(fetch)だけを偽物に差し替え、パース・勢い計算・並べ替え・
成人向けブロックは本物のまま回す(test-must-fail の線)。
"""
import time
import unittest

import scrape_5ch as s


def sjis(text: str) -> bytes:
    return text.encode("shift_jis")


class FakeNet:
    """URL→bytes の辞書で fetch を代替する偽物。"""
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, url, ua=s.BROWSER_UA, timeout=20):
        self.calls.append(url)
        for host_bad in s.BLOCKED_HOST_SUBSTR:
            if host_bad in url:
                raise ValueError("blocked")
        if url not in self.mapping:
            raise s.urllib.request.HTTPError(url, 404, "Not Found", {}, None)
        return self.mapping[url]


class TestParseSubject(unittest.TestCase):
    def test_parse_and_skip_garbage(self):
        text = "1700000000.dat<>テストスレ (123)\nゴミ行\n1700000001.dat<>二本目【速報】 (7)\n"
        rows = s._parse_subject(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["thread_id"], "1700000000")
        self.assertEqual(rows[0]["title"], "テストスレ")
        self.assertEqual(rows[0]["res_count"], 123)
        self.assertEqual(rows[1]["res_count"], 7)


class TestRank(unittest.TestCase):
    def test_momentum_and_order(self):
        now = 1700000000 + 86400  # スレ立てから1日後
        threads = [
            {"thread_id": str(1700000000), "title": "遅い", "res_count": 10},
            {"thread_id": str(1700000000), "title": "速い", "res_count": 500},
        ]
        ranked = s.rank_threads(threads, now=now)
        self.assertEqual(ranked[0]["title"], "速い")
        # 1日で500レス → 勢い≒500/日
        self.assertAlmostEqual(ranked[0]["momentum"], 500.0, delta=1.0)

    def test_no_zero_division_for_fresh_thread(self):
        now = 1700000000
        threads = [{"thread_id": str(1700000000), "title": "立て直後", "res_count": 3}]
        ranked = s.rank_threads(threads, now=now)  # age=0 → 下限60秒
        self.assertGreater(ranked[0]["momentum"], 0)
        self.assertLess(ranked[0]["momentum"], 1e7)


class TestParseDat(unittest.TestCase):
    def test_title_and_body_and_anchor(self):
        dat = (
            "名無し<>sage<>2026/09/02 12:00 ID:abc<>本文<br>2行目 &gt;&gt;1<>スレタイ【本物】\n"
            '名無し2<>sage<>2026/09/02 12:01 ID:xyz<><a href="../1/">&gt;&gt;1</a> レス<>\n'
        )
        d = s.parse_dat(dat)
        self.assertEqual(d["title"], "スレタイ【本物】")
        self.assertEqual(len(d["posts"]), 2)
        self.assertEqual(d["posts"][0]["body"], "本文\n2行目 >>1")
        # アンカーはテキスト化されタグは消える
        self.assertIn(">>1 レス", d["posts"][1]["body"])
        self.assertNotIn("<a", d["posts"][1]["body"])


class TestResolveBase(unittest.TestCase):
    def test_picks_richer_mirror(self):
        # bbsmenu は .io を返すが .io は貧弱・.net が豊富 → .net を選ぶ
        menu = 'A<a href=https://x.5ch.io/newsplus/>ニュース速報+</a>B'
        io_subj = "1700000000.dat<>a (1)\n"
        net_subj = "1700000000.dat<>a (1)\n1700000001.dat<>b (2)\n1700000002.dat<>c (3)\n"
        net = FakeNet({
            s.BBSMENU_URL: sjis(menu),
            "https://x.5ch.io/newsplus/subject.txt": sjis(io_subj),
            "https://x.5ch.net/newsplus/subject.txt": sjis(net_subj),
        })
        base = s.resolve_base("newsplus", fetcher=net)
        self.assertEqual(base, "https://x.5ch.net/newsplus")

    def test_missing_board_raises(self):
        net = FakeNet({s.BBSMENU_URL: sjis("no board here")})
        with self.assertRaises(LookupError):
            s.resolve_base("nosuchboard", fetcher=net)


class TestScrapeBoard(unittest.TestCase):
    def _net(self):
        menu = 'x<a href=https://srv.5ch.net/newsplus/>ニュース速報+</a>'
        now = int(time.time())
        old = now - 86400
        subj = "%d.dat<>普通のスレ (100)\n%d.dat<>爆速スレ (900)\n" % (old, old)
        dat_hot = "名無し<>sage<>日付ID<>爆速の1レス目<>爆速スレ\n"
        return FakeNet({
            s.BBSMENU_URL: sjis(menu),
            "https://srv.5ch.net/newsplus/subject.txt": sjis(subj),
            "https://srv.5ch.net/newsplus/dat/%d.dat" % old: sjis(dat_hot),
        })

    def test_hot_thread_first_and_bodies(self):
        net = self._net()
        res = s.scrape_board("newsplus", top_n=1, max_posts=10, fetcher=net, sleep=0)
        self.assertEqual(res["board"], "newsplus")
        self.assertEqual(res["thread_count_total"], 2)
        self.assertEqual(len(res["threads"]), 1)
        top = res["threads"][0]
        self.assertEqual(top["title"], "爆速スレ")            # 勢い順で爆速が1位
        self.assertEqual(top["res_count"], 900)
        self.assertEqual(len(top["posts"]), 1)
        self.assertIn("read.cgi/newsplus/", top["url"])       # 人が読むURLはread.cgi
        self.assertIsNone(top["fetch_error"])

    def test_dat_fetch_error_is_captured_not_fatal(self):
        # dat が404でもスレ単位で握って全体は完走する
        menu = 'x<a href=https://srv.5ch.net/newsplus/>N</a>'
        now = int(time.time()); old = now - 86400
        subj = "%d.dat<>取れないスレ (50)\n" % old
        net = FakeNet({
            s.BBSMENU_URL: sjis(menu),
            "https://srv.5ch.net/newsplus/subject.txt": sjis(subj),
        })  # dat は入れない → 404
        res = s.scrape_board("newsplus", top_n=1, fetcher=net, sleep=0)
        self.assertEqual(len(res["threads"]), 1)
        self.assertEqual(res["threads"][0]["posts"], [])
        self.assertIsNotNone(res["threads"][0]["fetch_error"])


class TestAdultBlocked(unittest.TestCase):
    def test_real_fetch_blocks_pink(self):
        with self.assertRaises(ValueError):
            s.fetch("https://foo.bbspink.com/erobbs/subject.txt")


if __name__ == "__main__":
    unittest.main()
