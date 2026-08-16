# -*- coding: utf-8 -*-
"""
persona_settings_index.py  —  人格設定ハブの「一覧」データ生成器(hrツール・C-019)

Chami依頼(2026-08-16 msg 1538499998671568906)の下地:
「差分やキャラクターの呼び方を設定されているところの一覧をページで作って欲しい」
= 設定が散らばる複数の正本を **キャラ別に1本へ集約** する。ページはこのJSONを描くだけ。

読むだけ(正本は一切書き換えない)。出力= local/persona_settings_index.json。
各キャラについて「どこに・何が設定されているか(所在)」+「機械で綺麗に解決できる値」を集める。
解決が曖昧な呼称は "所在" を指すに留める(推測で値を埋めない=共通規律§1)。

使い方: python scripts/hr/persona_settings_index.py
"""
import json, os, re, sys, io

# --- パス(cwd=5SecMovieMaker 前提) ---
HR   = os.path.join("..", "00_AI-HQ", "departments", "hr")
PERS = os.path.join(HR, "personas")
CHAR = os.path.join(HR, "characters")
LOCAL = "local"
AVATARS = os.path.join(LOCAL, "persona_avatars.json")
SPRITES = os.path.join(LOCAL, "persona_sprites")
CONTEXT = os.path.join(LOCAL, "persona_context")
OUT     = os.path.join(LOCAL, "persona_settings_index.json")
# 公開ページ(GitHub Pages)へ配信するJS埋め込み版。local/ はgitignore配下=Pagesに出ない
# ため、ページが読める persona-hub/ 直下に window.PERSONA_HUB_DATA として焼き込む(派生物・手編集禁止)。
DATAJS  = os.path.join("persona-hub", "data.js")

def _load_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[warn] {p}: {e}", file=sys.stderr)
        return {}

def _roster_map():
    """ROSTER.md の表から キャラ名 -> {file, dept, base} を作る。"""
    m = {}
    p = os.path.join(CHAR, "ROSTER.md")
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 3:
                    continue
                name, fname, dept = cells[0], cells[1], cells[2]
                if name in ("キャラ名", "") or "---" in name:
                    continue
                base = fname[:-3] if fname.endswith(".md") else None
                m[name] = {"characterfile": (os.path.join(CHAR, fname) if base else None),
                           "dept": dept, "base": base}
    except Exception as e:
        print(f"[warn] ROSTER: {e}", file=sys.stderr)
    return m

def build():
    roster   = _roster_map()
    tone     = _load_json(os.path.join(PERS, "口調ルール.json")).get("personas", {})
    yobi     = _load_json(os.path.join(PERS, "呼称ルール.json"))
    avatars  = _load_json(AVATARS)

    # 呼称: 対象別/話者別に索引化(所在の逆引き)
    sto = yobi.get("speaker_target_overrides", [])
    sto = [x for x in sto if isinstance(x, dict) and "speaker" in x]
    hrt = {k: v for k, v in yobi.get("honorific_required_targets", {}).items() if not k.startswith("_")}

    # 全キャラ集合 = ROSTER ∪ 口調 ∪ アイコン
    names = set(roster) | set(tone) | {k for k in avatars if not k.startswith("_")}

    out = {}
    for name in sorted(names):
        r = roster.get(name, {})
        base = r.get("base")
        av = avatars.get(name, [])
        entry = {
            "所属部門": r.get("dept"),
            "設定所在": {
                "原典_characterfile": r.get("characterfile"),
                "口調ルール": (os.path.join(PERS, "口調ルール.json") if name in tone else None),
                "呼称ルール": os.path.join(PERS, "呼称ルール.json"),
                "アイコン差分": (AVATARS if name in avatars else None),
                "スプライト": (os.path.join(SPRITES, base) if base and os.path.isdir(os.path.join(SPRITES, base)) else None),
                "文脈": (os.path.join(CONTEXT, base + "_context.md") if base and os.path.isfile(os.path.join(CONTEXT, base + "_context.md")) else None),
            },
            "口調": tone.get(name),  # 一人称/語尾/禁止語(verbatim・正本のまま)
            "アイコン": {
                "枚数": len(av),
                "url": av,
            },
            "呼称": {
                "この人をどう呼ぶか": {
                    "敬称必須(honorific_required)": hrt.get(name),
                    "Chami宛の例外": yobi.get("chami_address", {}).get("overrides", {}).get(name),
                    "自分を対象にした個別ルール": [x for x in sto if x.get("target") == name],
                },
                "この人が誰をどう呼ぶか": [x for x in sto if x.get("speaker") == name],
            },
        }
        out[name] = entry

    meta = {
        "_generated_by": "scripts/hr/persona_settings_index.py",
        "_note": "人格設定ハブの一覧データ。正本を集約した派生物=ここを手で編集しない。正本を直したら再生成する。",
        "_sources": {
            "口調": os.path.join(PERS, "口調ルール.json"),
            "呼称": os.path.join(PERS, "呼称ルール.json"),
            "アイコン": AVATARS,
            "原典": os.path.join(CHAR, "ROSTER.md"),
        },
        "_count": len(out),
    }
    return {"_meta": meta, "personas": out}

def main():
    data = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    # 公開ページ用に同じデータをJSへ焼き込む(fetch不要=404回避)。
    with open(DATAJS, "w", encoding="utf-8") as f:
        f.write("/* 自動生成: scripts/hr/persona_settings_index.py。手で編集しない。正本を直したら再生成する。 */\n")
        f.write("window.PERSONA_HUB_DATA = ")
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write(";\n")
    # コンソール文字化け回避のためASCIIで要約
    print("wrote", OUT)
    print("wrote", DATAJS)
    print("personas:", data["_meta"]["_count"])
    with_tone = sum(1 for v in data["personas"].values() if v["口調"])
    with_av   = sum(1 for v in data["personas"].values() if v["アイコン"]["枚数"] > 0)
    print("with_tone_rule:", with_tone, "/ with_avatar:", with_av)

if __name__ == "__main__":
    main()
