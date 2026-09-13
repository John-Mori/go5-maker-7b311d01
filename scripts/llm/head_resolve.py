#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部門長(head)の「名指し」を1か所で解く。

★なぜ在るか(2026-09-14・イージス研究室)=
  名指しの表が **3か所に手で写されていた**。
    ① 00_AI-HQ/org_registry.yml  depts.<dept>.managed_by  ← 両方のコメントが「正本」と書いていた
    ② scripts/llm/dispatch.py    NAMED_HEAD               ← 投函ガード側
    ③ scripts/llm/dept_daemon.py _head_dept() _NAMED_HEAD ← 常駐側
  そして実際に **②が12日間欠けていた**(goods-afi=2026-09-01 / someday-room=2026-09-02 に
  ③だけへ入り、②は head=None=素通し。2026-09-14 にHQが実測して発覚)。
  「両方に書け」とコメントで念を押しても止まらなかった= **心がけに任せた機構は落ちる**(共通規律§3)。
  → 読む口を1つにする。正本は①。①に無い分だけ②③の代わりに下の FALLBACK が受ける。

★fail-open を壊さない= yml が読めない・項が無い時は **None ではなく FALLBACK** へ落ちる。
  None を返すのは「名指しが無い」の意味であって「引けなかった」ではない(呼び側はカテゴリ表へ進む)。
"""
import os
import sys

ORG_REGISTRY = r"D:\SougouStartFolder\00_AI-HQ\org_registry.yml"

# ★正本(org_registry.yml)にまだ項が無い部門の補欠。
#   ここに在って yml に無い= 正本の取りこぼし。`--check` が名指しで鳴らす。
#   llm-growth: 2026-09-14 現在 depts に項が無い(HQ実測)。項が出来たらこの行を消す。
FALLBACK_HEAD = {
    "goods-afi": "aegis-gl",
    "someday-room": "hq",
    "llm-edu": "aegis-gl",
    "llm-qa": "aegis-gl",
    "llm-growth": "aegis-gl",
    "imagegen": "aegis-gl",
}

_cache = None


def _registry_heads():
    """org_registry.yml から {dept: managed_by} を読む。読めなければ空dict(=補欠へ落ちる)。"""
    global _cache
    if _cache is not None:
        return _cache
    out = {}
    try:
        import yaml
        with open(ORG_REGISTRY, encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        for k, v in (y.get("depts") or {}).items():
            if isinstance(v, dict) and v.get("managed_by"):
                out[str(k)] = str(v["managed_by"]).strip()
    except Exception:
        out = {}          # ★読めない時は黙って補欠へ。配達を殺さない。
    _cache = out
    return out


def named_head(dept):
    """名指しの部門長スラッグ。名指しが無ければ None(呼び側はカテゴリ表へ進む)。"""
    if not dept:
        return None
    reg = _registry_heads()
    if dept in reg:
        return reg[dept]
    return FALLBACK_HEAD.get(dept)


def named_depts():
    """名指しが効く部門の全集合(正本+補欠)。監査用。"""
    return set(_registry_heads()) | set(FALLBACK_HEAD)


def check():
    """正本と補欠のズレを鳴らす。戻り値= 問題の件数(0なら健全)。"""
    reg = _registry_heads()
    bad = 0
    if not reg:
        print("★org_registry.yml から managed_by を1件も読めなかった"
              f"(パス= {ORG_REGISTRY})。補欠{len(FALLBACK_HEAD)}件だけで走っている。")
        return 1
    print(f"正本(org_registry.yml depts.managed_by): {len(reg)}件")
    for d, h in sorted(reg.items()):
        print(f"  {d} -> {h}")
    for d, h in sorted(FALLBACK_HEAD.items()):
        if d not in reg:
            bad += 1
            print(f"★正本に項が無い(補欠で受けている): {d} -> {h}"
                  "  = org_registry.yml へ managed_by を足せば、この行は消してよい")
        elif reg[d] != h:
            bad += 1
            print(f"★正本と補欠が食い違う: {d} 正本={reg[d]} / 補欠={h}"
                  "  = 補欠の方を正本へ合わせろ(効いているのは正本)")
    print(f"問題: {bad}件")
    return bad


def orphans():
    """★恒久側= 「カテゴリ表に無い親の下に居て、名指しも無い部門」を列挙して鳴らす。

    今までこの穴は **事故ってから人が気づいて**塞いでいた(goods-afi 2026-09-01 /
    someday-room 2026-09-02 / ローカルLLM4室 2026-09-14)。次に新しいカテゴリが増えた日に
    また黙って外れる= 気づく係を機構にする(共通規律§3「心がけに任せない」)。

    Discordは **1コールだけ**叩く(GET /guilds/<id>/channels)。戻り値= 素通しになる部門の数。
    """
    import json
    import urllib.request
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import dispatch                      # LAYER_OF / CATEGORY_HEAD / LOCAL の正本はあちら

    guild = "1498341160207515678"
    tok = open(os.path.join(dispatch.LOCAL, "discord_bot_token.txt"),
               encoding="utf-8").read().strip()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/guilds/{guild}/channels",
        headers={"Authorization": f"Bot {tok}", "User-Agent": "go5/1.0"})
    chans = json.load(urllib.request.urlopen(req, timeout=20))
    parent = {str(c["id"]): str(c.get("parent_id") or "") for c in chans}
    catname = {str(c["id"]): c.get("name", "") for c in chans if c.get("type") == 4}

    # 部門長を持たない/持てない側は対象外(dispatch.head_of の先頭と同じ条件)
    exempt = ("hq", "research-room", "aegis-gl", "keiei-kikaku")
    # ★**意図して部門長を置いていない**カテゴリ。ここを外すと6室が毎回鳴り、
    #   「常に誤発火する安全網は無視される」(共通規律§3)へまっすぐ落ちる。
    #   根拠= dept_daemon.py:2424-2425「親カテゴリは『パーソナル Personal』…=head は None
    #   (隣室の kukuru-nakama と同じ扱い。_NAMED_HEAD には足さない)」= 明文の決定。
    #   ★新しいカテゴリを足す時にここへ書き足すのは「意図的に部門長を置かない」時だけだ。
    HEADLESS_CATEGORY = {
        "1527482687408046160": "パーソナル Personal(Chami個人の部屋=部門長を置かない)",
    }
    named = named_depts()
    bad = []
    with open(dispatch.CHANNELS, encoding="utf-8") as f:
        for c in json.load(f):
            d = c.get("dept")
            if not d or d in exempt or d in named:
                continue
            p = parent.get(str(c.get("id")), "")
            if dispatch.LAYER_OF.get(p):
                continue                 # カテゴリ表で引ける=健全
            if p in HEADLESS_CATEGORY:
                continue                 # 意図して置いていない=事故ではない
            bad.append((d, c.get("name", ""), p, catname.get(p, "(親なし)")))

    for d, nm, p, cn in sorted(bad):
        print(f"★素通し: {d}({nm}) 親カテゴリ「{cn}」{p} は LAYER_OF に無く、名指しも無い"
              "  = 上申が部門長を飛ばしてHQへ直行する")
    print(f"素通しの部門: {len(bad)}件 / 名指しで守られている部門: {len(named)}件")
    return len(bad)


if __name__ == "__main__":
    import sys
    if "--orphans" in sys.argv:
        sys.exit(1 if orphans() else 0)
    sys.exit(1 if check() else 0)
