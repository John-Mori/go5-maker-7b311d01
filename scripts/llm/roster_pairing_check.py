# -*- coding: utf-8 -*-
"""roster_pairing_check — 部屋の名簿が4本に分かれていて、片方だけ足すと部屋が無音になる事故を検知する。

なぜ要るか(2026-08-31・研究室HQ発注 / プラットフォームSE[一ノ瀬怜]実装):
  研究室HQが DEPT_CONF に部屋 goods-afi を足した(commit c68489b)。だが番人は立たなかった。
  理由= 番人が回す名簿 `daemon_keeper.py:DEPTS` は**別の名簿**で、そこに goods-afi が無かった。
  結果= 便は届く(gateway は discord_channels.json を60秒で自動追従するので 📮送信 は付く)のに、
  **既読✅も着手👀も付かず、返事も来ない**(既読/着手を押すのは dept_daemon 自身=デーモンが
  1体も居なければ原理的に付かない)。Chami が「既読はつかんね」と気づいて指摘した(msg 1543835140550295562)。

  「増減時は対で直せ」は今も daemon_keeper.py と claim_room.py の**コメント**に書いてある。
  書いてあっても踏んだ。名簿が対になっている箇所が4つあり、全部コメントで守られている(=機構ではない)。
  → 心がけではなく機構に載せる(C-038)。差集合を測って、食い違ったら鳴らす。

見ている4本の名簿と、満たすべき関係:
  1. DEPT_CONF                (scripts/llm/dept_daemon.py)      … 全デーモン部屋の正本
  2. DEPTS                    (scripts/_daemons/daemon_keeper.py) … 番人が spawn する部屋
  3. claim_room.SESSION_ROOMS (scripts/discord/claim_room.py)   … 本人セッションが名乗る白名簿
  4. progress_mark.SESSION_ROOMS (scripts/hooks/progress_mark.py) … 同上(進捗印を絞る白名簿)

  ・DEPT_CONF == DEPTS                     … どちらの差も事故(本命)。
      DEPT_CONF にあって DEPTS に無い → **部屋が無音**(今日の goods-afi)。
      DEPTS にあって DEPT_CONF に無い → 番人が設定の無い dept を回し続ける。
  ・claim_room.SESSION_ROOMS == progress_mark.SESSION_ROOMS … 白名簿2本は同一であるべき。
  ・SESSION_ROOMS ⊆ DEPT_CONF              … 名乗る部屋には必ずデーモン設定が要る(session-note の写しを書く)。

★読むだけ。**import しない**(dept_daemon は本体=読むだけで副作用が起きうる。診断が対象を動かしてはいけない)。
   ast で該当の代入だけを取り出す(load_dept_conf と同じ作法)。
★限界= 名簿の「綴りの一致」しか見ない。部屋が Discord に実在するか等は別の検査(検査1〜4)が持つ。

使い方(単体):
  python scripts/llm/roster_pairing_check.py           # 差集合を1画面で出す(異常があれば終了コード1)
呼び出し(relay_health 検査17 から):
  import roster_pairing_check as rpc ; r = rpc.scan()
"""
import ast
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # scripts/llm -> scripts -> ROOT

DEPT_DAEMON_PY = os.path.join(ROOT, "scripts", "llm", "dept_daemon.py")
KEEPER_PY = os.path.join(ROOT, "scripts", "_daemons", "daemon_keeper.py")
CLAIM_PY = os.path.join(ROOT, "scripts", "discord", "claim_room.py")
PMARK_PY = os.path.join(ROOT, "scripts", "hooks", "progress_mark.py")


def _names_of(src, varname):
    """src(Pythonソース文字列)から `varname = ...` を1つ探し、中の文字列名を集合で返す。

    DEPT_CONF は dict(キーが部屋名)、DEPTS は list、SESSION_ROOMS は tuple。
    dict ならキー、list/tuple なら要素の**文字列定数だけ**を拾う。見つからなければ None
    (=「名簿が無い/形が変わった」を呼び手が区別できるように、空集合と分ける)。
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", "") == varname for t in node.targets):
            continue
        v = node.value
        if isinstance(v, ast.Dict):
            return {k.value for k in v.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if isinstance(v, (ast.List, ast.Tuple)):
            return {e.value for e in v.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return None


def _read(path, override):
    if override is not None:
        return override
    with open(path, encoding="utf-8") as f:
        return f.read()


def scan(dept_daemon_src=None, keeper_src=None, claim_src=None, pmark_src=None):
    """4本の名簿を読み、満たすべき関係の破れを差集合で返す。

    引数にソース文字列を渡すとファイルの代わりにそれを読む(must-fail 検証用=
    判定と分岐は本物のまま、入力だけ差し替える)。
    返り値の dict:
      n_conf/n_keeper/n_claim/n_pmark : 各名簿の件数(None=名簿が読めなかった)
      conf_not_keeper : DEPT_CONF - DEPTS  (部屋が無音・本命)
      keeper_not_conf : DEPTS - DEPT_CONF  (設定の無い dept を番人が回す)
      claim_vs_pmark  : 白名簿2本の対称差 (どちらかに片寄り)
      session_not_conf: SESSION_ROOMS - DEPT_CONF (名乗る部屋にデーモン設定が無い)
      problems        : 上記4カテゴリの件数合計(0=健康)
    """
    conf = _names_of(_read(DEPT_DAEMON_PY, dept_daemon_src), "DEPT_CONF")
    keeper = _names_of(_read(KEEPER_PY, keeper_src), "DEPTS")
    claim = _names_of(_read(CLAIM_PY, claim_src), "SESSION_ROOMS")
    pmark = _names_of(_read(PMARK_PY, pmark_src), "SESSION_ROOMS")

    def diff(a, b):
        # どちらかが None(名簿が読めない)なら差は取らない=空(誤警報を出さない=fail-open寄り)。
        if a is None or b is None:
            return []
        return sorted(a - b)

    session = set()
    if claim is not None:
        session |= claim
    if pmark is not None:
        session |= pmark

    conf_not_keeper = diff(conf, keeper)
    keeper_not_conf = diff(keeper, conf)
    claim_vs_pmark = (sorted((claim | pmark) - (claim & pmark))
                      if (claim is not None and pmark is not None) else [])
    session_not_conf = diff(session if (claim is not None or pmark is not None) else None, conf)

    problems = (len(conf_not_keeper) + len(keeper_not_conf)
                + len(claim_vs_pmark) + len(session_not_conf))
    return {
        "n_conf": None if conf is None else len(conf),
        "n_keeper": None if keeper is None else len(keeper),
        "n_claim": None if claim is None else len(claim),
        "n_pmark": None if pmark is None else len(pmark),
        "conf_not_keeper": conf_not_keeper,
        "keeper_not_conf": keeper_not_conf,
        "claim_vs_pmark": claim_vs_pmark,
        "session_not_conf": session_not_conf,
        "problems": problems,
    }


def _fmt(r):
    lines = []
    lines.append("名簿の件数: DEPT_CONF=%s / DEPTS=%s / claim.SESSION_ROOMS=%s / pmark.SESSION_ROOMS=%s"
                 % (r["n_conf"], r["n_keeper"], r["n_claim"], r["n_pmark"]))
    if r["conf_not_keeper"]:
        lines.append("★DEPT_CONF にあって DEPTS に無い(=部屋が無音): " + ", ".join(r["conf_not_keeper"]))
    if r["keeper_not_conf"]:
        lines.append("★DEPTS にあって DEPT_CONF に無い(=設定の無い dept を番人が回す): "
                     + ", ".join(r["keeper_not_conf"]))
    if r["claim_vs_pmark"]:
        lines.append("★白名簿2本が食い違う(claim_room ⇔ progress_mark): " + ", ".join(r["claim_vs_pmark"]))
    if r["session_not_conf"]:
        lines.append("★名乗る部屋にデーモン設定が無い(SESSION_ROOMS - DEPT_CONF): "
                     + ", ".join(r["session_not_conf"]))
    if r["problems"] == 0:
        lines.append("破れなし= 4本の名簿は対で揃っている")
    return "\n".join(lines)


def main():
    r = scan()
    print(_fmt(r))
    return 1 if r["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
