#!/usr/bin/env python3
"""AIオフィス純粋関数のテスト(依存ゼロ・実行= python tests/test_office.py)。

改善書v1 K-11。ここで固定しているのは **実際に起きていた欠陥**(改善書の所見ID付き)。
壊したら落ちる=安いモデルでも同じ穴を踏まない土台にする。
"""
import datetime
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "office"))
from office_core import (  # noqa: E402
    PRESENCE_LABEL, bubble_state, canon_name, esc, is_jst_today, jst_str, latest_ts,
    normalize_dept, normalize_sprite_entry, normalize_sprites, parse_idle_text, parse_ts,
    pick_sprite, presence_state,
)

ok = fail = 0


def t(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS {name}")
    else:
        fail += 1
        print(f"  FAIL {name}\n       got : {got!r}\n       want: {want!r}")


print("T-1 部門slugの正規化 (F2/ORG-4: 旧slugのタスクが部屋から消えていた)")
t("dev→system-engineer", normalize_dept("dev"), "system-engineer")
t("kaizen→kaizen-analyst", normalize_dept("kaizen"), "kaizen-analyst")
t("日本語キー『司令塔』→research-room", normalize_dept("司令塔"), "research-room")
t("INDEX表記 incident-recovery→incident", normalize_dept("incident-recovery"), "incident")
t("未知slugは捨てず素通し(取りこぼし検知のため)", normalize_dept("newdept"), "newdept")
t("既知slugはそのまま", normalize_dept("system-engineer"), "system-engineer")

print("T-2 時刻の解釈 (F6: epochが生数字で画面に出る/オフセットで二重加算)")
t("D1標準形(UTC)→JST表示", jst_str("2026-07-13 23:52:47"), "07/14 08:52")
t("T区切り+小数秒", jst_str("2026-07-13T23:52:47.123"), "07/14 08:52")
t("Z付きUTC", jst_str("2026-07-13T23:52:47Z"), "07/14 08:52")
t("+09:00付きは二重加算しない", jst_str("2026-07-14T12:00:00+09:00"), "07/14 12:00")
t("epoch秒は生数字を出さない", jst_str(1752624000), "07/16 09:00")
t("epochミリ秒", jst_str(1752624000000), "07/16 09:00")
t("None→空", jst_str(None), "")
t("壊れた値は生のまま出さず空", jst_str("なんだこれ"), "")
t("parse_ts(None)", parse_ts(None), None)

print("T-3 JST暦日での『本日』(F3: UTC暦日で数えJST 0-9時の完了が消えていた)")
now = datetime.datetime(2026, 7, 17, 2, 0, 0)          # UTC 02:00 = JST 11:00 (同じ7/17)
t("JST未明の完了は本日に入る", is_jst_today("2026-07-16 22:30:00", now), True)   # =JST 7/17 07:30
t("JST前日夜は本日でない", is_jst_today("2026-07-16 14:00:00", now), False)      # =JST 7/16 23:00
t("解釈不能は本日でない", is_jst_today("", now), False)

print("T-4 最新時刻の判定 (F6: 文字列maxは 'T'>' ' で書式混在時に誤る)")
t("書式混在でも実時刻で最新", latest_ts(["2026-07-13T23:00:00", "2026-07-14 08:00:00"]), "2026-07-14 08:00:00")
t("空・None混在に耐える", latest_ts([None, "", "2026-07-14 08:00:00"]), "2026-07-14 08:00:00")
t("全部ダメなら空", latest_ts([None, ""]), "")

print("T-5 在席の3状態 (INC-94: 脈は配達の瞬間に止まる=脈なしを『不在』と断定してはいけない)")
t("新鮮=在席", presence_state(1000.0, 1100.0), "active")
t("601秒前=脈なし(不在と断定しない)", presence_state(1000.0, 1601.0), "stale")
t("脈ファイル無し=未計測", presence_state(None, 1601.0), "none")
t("staleのラベルが不在と断定していない", PRESENCE_LABEL["stale"], "脈なし(不在または処理中)")
t("activeのラベル", PRESENCE_LABEL["active"], "在席(チャイム待機中)")

print("T-6 バブル状態の導出 (実データのみが根拠)")
t("承認待ちが最優先", bubble_state([{"status": "done"}, {"status": "blocked"}, {"status": "in_progress"}]), "blocked")
t("作業中", bubble_state([{"status": "done"}, {"status": "in_progress"}]), "work")
t("仕事箱", bubble_state([{"status": "open"}, {"status": "done"}]), "queue")
t("完了のみ=待機", bubble_state([{"status": "done"}]), "idle")
t("タスクゼロ=待機", bubble_state([]), "idle")

print("T-7 立ち絵台帳の3形式 (SPR-5: オタコンだけ別形式でパス基準も違う)")
t("素の文字列", normalize_sprite_entry("persona_sprites/kukuru/a.png"),
  {"img": "persona_sprites/kukuru/a.png", "label": "", "when": ""})
t("{img}形式", normalize_sprite_entry({"label": "閃き", "when": "閃いた時", "img": "persona_sprites/mitoma/b.jpg"}),
  {"img": "persona_sprites/mitoma/b.jpg", "label": "閃き", "when": "閃いた時"})
t("{file}形式(オタコン)はパス基準を補って吸収",
  normalize_sprite_entry({"file": "otacon/normal_1.png", "src": "discord"}),
  {"img": "persona_sprites/otacon/normal_1.png", "label": "", "when": ""})
t("画像未提供の予約枠はNone(琴葉rare)", normalize_sprite_entry({"label": "スイーツ接種中", "img": None}), None)
t("Noneエントリ", normalize_sprite_entry(None), None)

led = {
    "_meta": {"about": "無視される"},
    "ククール": {"role": "説明文は取り込まない", "normal": ["persona_sprites/kukuru/a.png"],
                 "mischief": ["persona_sprites/kukuru/m.png"]},
    "ホイミン(Gemini)": {"role": "立ち絵なし=載らない"},
    "オタコン": {"normal": [{"file": "otacon/normal_1.png"}]},
}
n = normalize_sprites(led)
t("_metaとroleは落ちる", sorted(n.keys()), ["オタコン", "ククール"])
t("カテゴリだけ残る", sorted(n["ククール"].keys()), ["mischief", "normal"])
t("オタコンのパスが正規化されている", n["オタコン"]["normal"][0]["img"], "persona_sprites/otacon/normal_1.png")

print("T-8 状態→立ち絵の写像 (演出は待機時のみ・根拠は実status)")
rng = random.Random(1)
cats = {"normal": [{"img": "n.png", "label": "", "when": ""}],
        "talking": [{"img": "t.png", "label": "", "when": ""}],
        "mischief": [{"img": "m.png", "label": "", "when": ""}],
        "emergency": [{"img": "e.png", "label": "", "when": ""}]}
t("作業中は語り", pick_sprite(cats, "work", rng)[0], "t.png")
t("承認待ちは緊急", pick_sprite(cats, "blocked", rng)[0], "e.png")
t("仕事箱は通常(演出を出さない)", pick_sprite(cats, "queue", rng)[0], "n.png")
t("待機は演出フラグが立つ", pick_sprite(cats, "idle", rng)[2], True)
t("作業中は演出フラグが立たない", pick_sprite(cats, "work", rng)[2], False)
t("立ち絵ゼロならNone", pick_sprite({}, "work", rng), None)
t("該当カテゴリ皆無ならNone", pick_sprite({"insight": [{"img": "i.png"}]}, "queue", rng), None)

print("T-9 名前の名寄せ (ORG-8: 完全一致依存で台帳を引けない)")
t("フルネーム→台帳キー", canon_name("ケヴィン・デブライネ"), "デブライネ")
t("中黒ゆれ", canon_name("ケヴィン・デ・ブライネ"), "デブライネ")
t("兼任印を落とす", canon_name("オタコン(兼)"), "オタコン")
t("括弧付き別名", canon_name("オタコン(ハル・エメリッヒ)"), "オタコン")
t("補佐印を落とす", canon_name("アメス(補佐)"), "アメス")
t("markdown強調を落とす", canon_name("**黒川あかね**"), "黒川あかね")
t("読み仮名付き", canon_name("中野五月(なかのいつき)"), "中野五月")
t("素の名前はそのまま", canon_name("花海咲季"), "花海咲季")

print("T-10 idle演出テキストの取り出し (ORG-7: 正本はmanifest)")
t("単数", parse_idle_text("待機中の特殊演出(稀に発生・おまけ)=自主トレ中"), ["自主トレ中"])
t("複数", parse_idle_text("待機中の特殊演出(稀・おまけ)=野良猫と会話中 / 昼寝中"), ["野良猫と会話中", "昼寝中"])
t("空", parse_idle_text(""), [])
t("=無しはそのまま1件", parse_idle_text("お風呂中"), ["お風呂中"])

print("T-11 esc (切り詰め→エスケープの順序)")
t("エスケープされる", esc('<script>"x"'), "&lt;script&gt;&quot;x&quot;")
t("切り詰めは実体参照を割らない", esc("<" * 5, 3), "&lt;&lt;&lt;…")

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
