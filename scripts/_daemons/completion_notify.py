#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""依頼が完遂したら、**発注元の部屋へ1行だけ**自動で返す(2026-09-04・aegis-gl)。

なぜ要るか(実物・HQアロンソ発注 msg=1545275628134072442):
  2026-09-04 03:15、ad研究室が2部門へ発注した。
    分析部門(骨格)= msg 1545135253847277648 / コピー部(文言)= msg 1545135261816717432
  **両部門とも同日03:2xに完遂して `local/consult_intel/` へ成果を置いていた。**
  それでも発注元のad研究室は **12:00まで知らなかった**。8時間半、実在する完遂を未達として
  持ち回った。見えなかった理由は3つ重なっている=
    ① 成果は便ではなく**置き場**に落ちる(誰も鳴らさない)
    ② `local/` は gitignore なので `git log` にも出ない
    ③ `request_log.jsonl` には `completed`/`replied` と着地msg_idが**両方入っていた**
  → **機械は完遂を知っていて、発注元だけが知らなかった。**

  HQは共通規律§3.8へ「請けた側は問われる前に発注元へ1行返せ」を入れて止血した(commit
  2a4e69d / repo=00_AI-HQ)。だがそれは人手を規律で縛っただけで、**請けた部門が忘れれば
  同じ穴がまた開く**。恒久は機械側にしか置けない=これがその機械だ。

★設計で一番効いた実測= **発注元が機械のどこにも記録されていなかった。**
    - `request_log.jsonl` の項目は {request_id, dept, state, ts, evidence} だけ
    - `dispatch.py` は `--from-dept` を受け取るのに**便レコードへ載せていなかった**
      (呼称ゲートに渡して捨てていた)
    - `local/discord_processed.jsonl` の dispatch 便**1721件すべてに from_dept が無い**
    - 発注元は本文に**人間の言葉でだけ**書かれていた(「■戻し先 結果は consult-intel へ」)
  → 先に `dispatch.py` の便レコードへ `from_dept` / `from_dept_explicit` を足した
    (2026-09-04・新規キーの追加のみ=既存を壊さない)。**この常駐は、それ以降の便にしか
    効かない。**過去の便に発注元は書かれていないので、遡って救うことはできない。

やらないこと(意図して):
  - **本体を運ばない**(C-023/C-050の線)。出すのは「完遂した」「何の依頼だったか」
    「請けた部屋のどのメッセージに着地したか」だけ。成果そのものは置き場にある。
  - **本文の全文は運ばない**(下の「置き場のパス」も、運ぶのは**パス1本だけ**)。
  ★2026-09-05 訂正(C-071・HQ裁定 00_AI-HQ `93342a8`)= 初版はここに
    「**置き場のパスは名乗らない= 機械が知らないからだ**」と書いていた。**それは嘘だった。**
    実測= ad研究室が同夜3通の完遂通知を受け、答えに辿り着けたのは成果がたまたま紙だった1通だけ。
    残り2通で「成果の在りかはそこに書いてある」は**偽**だった(2/3が空振り)。
    機械は「知らない」のではなく、**持っているのに読んでいなかった**= 下の `spot`(置き場)を参照。
  - **推定で宛先を決めない。**`author`(人格名)から部門を逆引きする案は捨てた=同じ人格が
    複数の部屋に居るので静かに誤配する。発注元が決まらない便は**鳴らさず**、標準出力へ残す。

置き場のパスを1本だけ運ぶ(C-071・2026-09-05):
  HQの指示は「着地msg_idをキーに `local/discord_processed.jsonl` から返信の `content` を引け」
  だった。**その台帳では引けない**= 実測で **着地msg_id 4365本のうち 0本**しか居ない。
  あの台帳に載るのは**受け取った便**(dispatch/Chami発)だけで、請けた側が部屋へ**出した**返信は
  一度も戻ってこないからだ。指示の狙い(機械は持っている)は正しいが、置き場が違う。
  実際に本文を持っているのは次の2つ=
    ① `local/llm/send_audit.jsonl` … 送信台帳。`msg_id` と `body` が並ぶ。**着地msg_idで直に引ける**。
       ★ただし `body` が入り始めたのは **2026-09-04T23:25:29** から(977行中76行)。それ以前の便では
         空振りする= 過去は救えない、これから効く(from_dept の時と同じ形)。
    ② `local/llm/recent_<dept>.jsonl` … 部屋ごとの直近6往復。**依頼のmsg_id(=request_id)**で
       引ける代わりに、返信は700字で切られている。①が無い時の控えとして使う。
  拾ったパスは `os.path.exists` で**実在を確かめてからしか案内しない**(FP対策)。
  拾えなかった時は「**そこに書いてある**」と言わずに、**見つからなかったと書く**(推定で埋めない=§1)。

冪等(要件2「同じ依頼で二度鳴らすな」):
  鳴らしたら request_log へ `completion_notified` を**追記**する。既存行は1行も書き換えない。
  次回はその request_id を対象から外す。★鳴らせなかった件は追記しない=状況が変われば拾える。

二重の抑制(要件3):
  請けた部門が自分で発注元の部屋へ1行返していたら鳴らさない。判定は
  「完遂時刻より後に、`dept=発注元` かつ `from_dept=請けた側` の dispatch 便がある」。
  ★dispatch を通さず部屋で直に返した場合は見えない=そのときは二重に鳴る(害は小さい方を採る)。
  ★★**1通の返信は1件の完遂しか打ち消さない**(2026-09-04・qa-reviewer(ジェンティルドンナ)
    指摘 msg=1545281379862843414)。初版は「そのペアに返信便が1通でもあれば抑える」だった=
    同じ2部門の間で依頼が**並走**すると、請けた側が1件だけ返しただけで残り全部が「返済み」と
    誤判定され、**黙って落ちる**。この常駐が潰したかった穴が抑制側から再発する形だ。
    → 使った返信便を消費して二度は使わない(N件完遂・M通返信なら max(0, N-M)件が鳴る)。
    ★どの依頼への返信かは便のどこにも書かれていない= 機械には区別できないので**件数だけで
      倒す**(fail-open= 分からない分は鳴らす側へ)。厳密化には返信便へ依頼IDを載せる入口が
      要るが、`--from-dept` が実測0件だった前科がある=人手の入口は増やさない判断。

fail-open(要件4):
  1件の失敗は他を止めない。全体の例外も握って exit 0 で終わる。**鳴らないことより、
  他を巻き込んで止まることの方が高くつく。**

使い方:
  python scripts/_daemons/completion_notify.py --dry-run   # 判定だけ・投函も追記もしない
  python scripts/_daemons/completion_notify.py             # 本番
  python scripts/_daemons/completion_notify.py --min-age-min 15 --since-hours 24
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
REQUEST_LOG = os.path.join(LOCAL, "llm", "request_log.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")
SEND_AUDIT = os.path.join(LOCAL, "llm", "send_audit.jsonl")   # ★C-071 返信の本文はここに在る
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
JST = dt.timezone(dt.timedelta(hours=9))

DONE_STATES = ("completed", "replied")
NOTIFIED_STATE = "completion_notified"
# ★請けた側が本文末に `<<WIP>>` を立てた印(dept_daemon が記帳する)。完遂と同居しうる。
WORKING_STATE = "working_detected"

# ★★この常駐が出す便の名義(2026-09-04・品質管理部門ジェンティルドンナ指摘 msg=1545296750602887228)。
#   **書く側(send)と読む側(main の除外)が同じ1本を引く**= 名義を変えても鎖の切断が外れない。
#   ここを別々の文字列で持つと、片方だけ直した日に鎖が黙って復活する(C-064と同じ向き)。
AUTO_SENDER = "完遂通知(自動)"


def parse_ts(s):
    """request_log の ts は tz なしの JST 表記。失敗したら None(その行は触らない)。"""
    try:
        return dt.datetime.fromisoformat(str(s)).replace(tzinfo=JST)
    except Exception:
        return None


def load_requests():
    """request_log を1回だけ舐めて (完遂した依頼, 通知済みID, WIPの最終時刻) を返す。

    完遂= {request_id: {"dept":…, "ts":…(最初のcompleted/replied), "evidence":…}}
    ★`replied` の evidence には請けた側の着地 `discord_msg=` が入っている。あとで
      「どこに落ちたか」を1行に入れるために、replied を見たら evidence を優先で採る。

    ★★2026-09-05(ad研究室/ルカ・モドリッチ 報告 → イージス研究室 経由でHQへ)=
      `working_detected`(請けた側が本文末に `<<WIP>>` を立てた印)を**この関数が捨てていた**。
      実物= req `DISPATCH-system-engineer-1788573797865` で 11:15:18 `completed` の
      **8秒後**に 11:15:26 `working_detected` が立ち、16分後に完遂だけが発注元へ届いた。
      → WIPの**最終時刻**を rid ごとに拾って返す。完遂より後に立っていたら、通知本文へ
        「完遂扱いにするな」の1行を混ぜる(判定を人の注意力に戻さない= §3 心がけに任せない)。
      ★完遂より**前**のWIPは正常な途中経過なので数えない(作業中→完遂は普通の流れ)。
    """
    done, notified, working = {}, set(), {}
    if not os.path.exists(REQUEST_LOG):
        return done, notified, working
    with open(REQUEST_LOG, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if '"state"' not in ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue          # 壊れた行は黙って飛ばす(台帳全体を止めない)
            rid, st = r.get("request_id"), r.get("state")
            if not rid:
                continue
            if st == NOTIFIED_STATE:
                notified.add(rid)
                continue
            if st == WORKING_STATE:
                # ★同じ rid に何度も立つ。**いちばん新しい1本**だけ残す(完遂との前後で使う)。
                ts = str(r.get("ts") or "")
                if ts and ts > working.get(rid, ""):
                    working[rid] = ts
                continue
            if st not in DONE_STATES:
                continue
            cur = done.get(rid)
            if cur is None:
                done[rid] = {"dept": r.get("dept") or "", "ts": r.get("ts") or "",
                             "evidence": r.get("evidence") or "", "state": st}
            elif st == "replied" and cur.get("state") != "replied":
                # 着地msg_idを持っている方(replied)を採る。時刻は最初の完遂のまま残す。
                cur["evidence"] = r.get("evidence") or cur["evidence"]
                cur["state"] = "replied"
    return done, notified, working


def load_letters(want_ids):
    """discord_processed から、欲しい msg_id の便レコードと「返した形跡」を集める。

    返り値 = (letters, replies)
      letters[msg_id] = 便レコード(発注そのもの。ここから from_dept を採る)
      replies = {(宛先dept, 送り主dept): [ts, …]}   ← 要件3の抑制に使う
    ★1回の走査で両方を作る(8MBを2度読まない)。
    """
    letters, replies = {}, {}
    if not os.path.exists(PROCESSED):
        return letters, replies
    with open(PROCESSED, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if '"via"' not in ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            mid = str(r.get("msg_id") or "")
            if mid and mid in want_ids:
                letters[mid] = r
            fd = (r.get("from_dept") or "").strip()
            if fd and r.get("dept"):
                replies.setdefault((r["dept"], fd), []).append(r.get("ts") or "")
    return letters, replies


def landed_msg(evidence):
    """evidence の `discord_msg=…` を取り出す(請けた側の返信の着地先)。

    ★戻り値は台帳の字面のまま(カンマ連結のことがある)。**idの集合が欲しい時は
      `landed_ids()` を使う**= ここを split すると "a,b" を1本のidとして扱ってしまう。
    """
    ev = evidence or ""
    i = ev.find("discord_msg=")
    if i < 0:
        return ""
    return ev[i + 12:].split()[0].strip() if ev[i + 12:].split() else ""


def landed_ids(evidence):
    """着地msg_idを**全部**返す(HQ-0242・2026-09-05)。

    ★1件の返信が人格ごとのブロックに割れて複数通出る部屋がある(hq= アロンソ+アメス)。
      2026-09-05の実測= `request_log.jsonl` の `replied` のうち送信台帳で引けた346行中
      **53行が多ブロック**で、実在するパスは**兄弟の投稿側に9本・記帳された側に0本**。
      1本に絞ると、答えではなく相槌を読むことになる= C-071 が空振りしていた真因。
    ★書く側(`dept_daemon.verify_replied`)がカンマで並べる。古い行は1本のまま=そのまま通る。
    ★`-`(着地不明)は id ではない= 落とす。
    """
    raw = landed_msg(evidence)
    return [m for m in (x.strip() for x in raw.split(",")) if m and m != "-"]


# ★C-071 置き場のパスらしき文字列。`local/…` `docs/…` から始まる塊を拾う。
#   - 直前が英数字・`_`・`.`・`-` なら拾わない(`mylocal/…` のような別語を切り出さないため)。
#     ★`\` と `/` は除いていない= 絶対パス `D:\…\5SecMovieMaker\local\x.md` の尾を拾うため。
#   - 括弧や読点、コードの囲みは終端として扱う(本文の続きを飲み込まない)。
#   - ★`00_AI-HQ/` を足した(2026-09-05)。実物= hr-room の返信 msg 1545529844522164286 が
#     「置き場= `00_AI-HQ/status/hq_open_items.md` の HQ-0226」と名乗っていたのに、
#     この正規表現が `local|docs` しか見ていなかったので『見つからなかった』で外した。
#     組織の台帳・裁定・status は 00_AI-HQ 側に在る= 拾えないと C-071 が半分しか効かない。
SPOT_RE = re.compile(r"(?<![0-9A-Za-z_.\-])((?:local|docs|00_AI-HQ)[\\/][^\s\u3000`\"'、。()（）「」『』\[\]<>*|]+)")
SPOT_TRIM = "。、,.:;`*)）」』】>\"'"

# 拾ったパスの実在を確かめる時の起点。`00_AI-HQ/` は repo の**外**(D:\SougouStartFolder\00_AI-HQ)
# に在るので、ROOT を足すと必ず存在しないことになる= 静かに全部落ちる。
SPOT_OUTSIDE = ("00_AI-HQ/",)


def spot_abs(rel):
    """相対パスを、実在を確かめられる絶対パスへ直す(起点が repo の外の場合が在る)。

    ★`ROOT` はモジュール変数を都度読む= テストが根を差し替えても付いてくる。
    """
    if rel.startswith(SPOT_OUTSIDE):
        return os.path.join(os.path.dirname(ROOT), rel)
    return os.path.join(ROOT, rel)

# ★「置き場だ」と本文が名乗っている語。パスの**直前 SPOT_NEAR 字**に在れば、それが本命。
#   ★窓を80字・語を「答え/紙/成果」まで広げたら実測で誤爆した= 「便2の答えは…」の直後に
#     根拠として引かれた `local/discord_processed.jsonl` を成果と読んだ。散文に混ざる語は
#     信号にならない。**名乗りの形(置き場= …)に近い語だけ・窓は狭く**。
SPOT_WORDS = ("置き場", "置いた", "置いてある", "置きました", "置く先", "成果物", "納品",
              "保存先", "出力先", "落とした", "落としました", "作成した", "正本は")
SPOT_NEAR = 24
# 答えの紙が集まる場所(名乗りが無くても、ここに在るなら成果と読んでよい)。
# ★ここを `docs/` まで広げない= 参照した規約や設計書を成果と読み違える。
SPOT_DIRS = ("local/consult_intel/", "docs/departments/")


def find_spot(text):
    """返信の本文から「実在する」置き場のパスを1本だけ拾う(C-071)。

    ★FP対策は二段=
      ① `os.path.exists` で**実在を確かめる**。無い場所は案内しない(知らないものを書かない・§4.55)。
      ② ★実在するだけでは足りない。返信は根拠として `local/…` のログや台帳を平気で引用する
         (実測= `local/discord_processed.jsonl` / `local/_reload_keeper.log` を拾ってしまった)。
         それを「成果の置き場」と呼べば、**2/3が偽だった元の穴を向きを変えて再現する**だけだ。
         → 本文が置き場だと名乗っている(直前80字に SPOT_WORDS)か、答えの紙が集まる場所
           (SPOT_DIRS)に在るものだけを採り、**どちらでもなければ拾わない**。
    ★1本だけ= 本体を運ばないという線(C-023/C-050)は動かさない。運ぶのは指先だけだ。
    """
    best = ""
    for m in SPOT_RE.finditer(text or ""):
        rel = m.group(1).replace("\\", "/").rstrip(SPOT_TRIM)
        if not rel or rel.endswith("/"):
            continue
        try:
            if not os.path.exists(spot_abs(rel)):
                continue
        except Exception:
            continue        # 変な文字列で落ちない(fail-open)
        near = (text or "")[max(0, m.start() - SPOT_NEAR):m.start()]
        if any(w in near for w in SPOT_WORDS):
            return rel      # 名乗りが在る= これが本命。以降は見ない
        if not best and rel.startswith(SPOT_DIRS):
            best = rel      # 次点。名乗り付きが後から出てきたらそちらを採る
    return best


def load_reply_bodies(landed_ids):
    """送信台帳(send_audit)から、着地msg_idの本文を引く。★1回走査。

    `msg_id` は分割送信で複数入ることがある(空白/カンマ区切り)ので、割ってから照合する。
    ★`body` を持たない行は飛ばす= 2026-09-04 23:25 より前の送信には本文が無い。
    """
    out = {}
    if not landed_ids or not os.path.exists(SEND_AUDIT):
        return out
    with open(SEND_AUDIT, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if '"msg_id"' not in ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            body = r.get("body") or ""
            if not body:
                continue
            for mid in str(r.get("msg_id") or "").replace(",", " ").split():
                if mid in landed_ids:
                    out[mid] = body
    return out


def recent_reply(dept, rid):
    """控えの取り出し口= 部屋ごとの直近6往復から、その依頼への返信を引く。

    ★キーは**依頼のmsg_id**(request_id)。送信台帳に本文が無い古い便でも、部屋がまだ
      覚えていれば拾える。★700字で切られているので、拾えないこともある(その時は黙る)。
    """
    p = os.path.join(LOCAL, "llm", f"recent_{dept}.jsonl")
    if not rid or not os.path.exists(p):
        return ""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if str(rid) not in ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if str(r.get("msg_id") or "") == str(rid):
                    return r.get("reply") or ""
    except Exception:
        pass
    return ""


def already_replied(replies, to_dept, from_dept, after, consumed):
    """請けた側(from_dept)が発注元(to_dept)へ、完遂の**後**に自分で便を出しているか。

    ★**1通の返信は1件の完遂しか打ち消さない**(qa-reviewer指摘・上のdocstring参照)。
      使った便の位置を `consumed[(to,from)]` へ入れ、同じ実行の中で二度は使わない。
      並走している依頼のうち返信が足りない分は**鳴る側へ倒す**(黙って落とすより二重が安い)。
    """
    key = (to_dept, from_dept)
    used = consumed.setdefault(key, set())
    for i, ts in enumerate(replies.get(key, [])):
        if i in used:
            continue
        t = parse_ts(ts)
        if t and t >= after:
            used.add(i)
            return True
    return False


def build_body(rid, dept, letter, done, landed, spot="", had_text=False, wip_ts=""):
    """発注元の部屋へ出す本文。★短く。本体は運ばない(C-023/C-050)。運ぶのはパス1本まで。

    ★HQ-0242(2026-09-05)= `had_text` を足した。**返信の本文を読めているのに
      「請けた部門へ問い直せ」と書くのは事故**だ(HQ原文=「既に届いている答えを
      問い直しに行く事故になる」)。紙が無い便は珍しくない= 口頭で答え切っている返信は
      置き場を持たない。その時に要るのは問い直しではなく**返信そのものを読むこと**。
      問い直せと言うのは、本文すら引けなかった時だけにする。
    """
    work = (letter.get("work") or "").strip()
    lines = [f"[完遂通知] {dept} が請けた依頼が**完遂**した(自動・request_log発)。"]
    if work:
        lines.append(f"■依頼= {work}")
    lines.append(f"■記帳= request_id `{rid}` / state `{done['state']}` / {done['ts']}")
    if wip_ts:
        # ★完遂の**後**に `<<WIP>>` が立っている= 請けた側はまだ続けている。
        #   ここを読み落とすと「完遂した」だけが独り歩きする(2026-09-05 ad研究室の実測)。
        lines.append(f"★**請けた側は `<<WIP>>` を立てている({wip_ts})= 完遂扱いにするな。**"
                     "この便の『完遂』は記帳上の1状態にすぎない。**続きが来るまで閉じるな。**")
    if landed:
        lines.append(f"■請けた側の返信= msg `{landed}`")
    else:
        lines.append("■請けた側の返信= 記帳に着地msg_idが無い(部屋を直接見てくれ)")
    if spot:
        # ★実在を確かめたパスだけがここへ来る(find_spot)。中身は運ばない。
        lines.append(f"■成果の置き場= `{spot}`(返信本文から拾って実在を確認した)")
    elif had_text:
        # ★返信は読めている= 紙が無いだけ。問い直せとは言わない(HQ-0242)。
        lines.append("■成果の置き場= **置き場のパスは無い。ただし返信そのものは届いている**"
                     f"{('(msg `' + landed + '`)') if landed else ''}= "
                     "**問い直す前にその返信を読め**(機械は推測で埋めない)。")
        lines.append("※紙を伴う仕事なら `local/` の下へ1枚置いてパスを返信に書いてもらえると、"
                     "次からここに載る(コードの直しは commit と change_log で追えるので不要)。")
    elif landed and done.get("state") == "replied":
        # ★★古い send_audit は本文ミラーを持たないが、`replied` + 着地msg_idは
        #   「請けた側が実際に返信を投稿した」ことの機械的な証拠だ。従来は
        #   本文をローカルに拾えないだけで「請けた部門へ問い直せ」と指示し、
        #   完遂→再質問→再完遂の往復を生んでいた。着地が実証済みなら再質問は不要。
        lines.append("■成果の着地= **返信済みを記帳で確認済み**"
                     f"(msg `{landed}`)。古い送信台帳のため本文ミラーは無いが、"
                     "**請けた部門へ再度問い直す必要はない**。")
    else:
        lines.append("■成果の置き場= **この便に置き場のパスは見つからなかった。請けた部門へ問い直せ**"
                     "(機械は推測で埋めない)。")
        lines.append("※調査・設計・可否判断の答えなら `local/` の下へ1枚置いてパスを返信に書いて"
                     "もらえると、次からここに載る(コードの直しは commit と change_log で追えるので不要)。")
    lines.append("★本体はここへ運んでいない(C-023/C-050)。**この便は完遂を知らせるだけだ。**")
    lines.append("※これは往路の**復路**なので3階梯を通していない(自動通知・completion_notify)。")
    return "\n".join(lines)


def quiet_ack_ok(spot, had_text, landed="", state=""):
    """この便が**手番ゼロ**か(=受け手に頼むことが1つも無いか)。判定はここ1箇所だけ。

    ★build_body の枝と1対1で対応させる= 置き場を載せた便 / 返信そのものが既に届いている便 /
      `replied` + 着地msg_idが記帳された便は「問い直せ」を書かない=手番ゼロ。
      それ以外の便は本文に
      「請けた部門へ問い直せ」と書く=**手番が有る**ので宣言しない(=今までどおり表へ出る)。
    """
    return bool(spot or had_text or (landed and state == "replied"))


# ★★2026-09-13・イージス研究室(デブライネ)指摘 msg=1548697831382978773=
#   従来の `and not wip_ts` は WIP が立っていれば**一律**畳まなかった。実データで検算した
#   (request_log.jsonl の wip 抑止行 44件・全件を replay)=
#     ・「畳んでいたら実際に失っていたはずの件」は **to_dept=hq の1件だけ**
#       (2026-09-13T19:11:25 の完遂通知→HQが読んで「git add -A を使うな」と指示→
#        同tree内の他部門の未commit差分961件を巻き込む事故を回避。change_log.jsonl 実物で確認)。
#     ・残り34件(hq以外の to_dept)は、同時間帯±2hの change_log.jsonl を事故語彙
#       (事故/見落とし/炎上/止めた/危な/誤発火/間違え/取り消し/止まった)で突き合わせても、
#       ヒットした9件は全て**無関係な別件の作業記録**(通常語彙が一致しただけ)で、
#       この便を畳んだこと自体が原因の損失は1件も無かった。
#   → 例外は **to_dept=hq だけ**にする(n=1の実例を一般化し過ぎない=fail-open側へ残す)。
#     hq 以外は WIP が立っていても、手番ゼロの基底判定(quiet_ack_ok)に従って畳んでよい。
WIP_FOLD_NEVER_DEPTS = ("hq",)


def wip_fold_ok(base_quiet, wip_ts, to_dept):
    """WIPが立っている便でも畳んでよいか。実データで唯一裏づけられた例外=to_dept が hq。

    ★本文もmsg内容も読まない(quiet_ack_target と同じ筋=構造だけで決める)。
      wip_ts が無い便はそもそもこの関数の出番ではない(=base_quiet をそのまま返す)。
    """
    if not wip_ts:
        return base_quiet
    if to_dept in WIP_FOLD_NEVER_DEPTS:
        return False
    return base_quiet


def send(to_dept, from_dept, body, dry_run, quiet_ok=False):
    """dispatch.py で1行返す。戻り値=(ok, 出力). ★--also-post は付けない(裏=キューだけ)。

    ★quiet_ok(2026-09-05 aegis-gl / DEF-persona-verxina-triage-register-20260905 #2)=
      **この便は手番ゼロだ**と機械が宣言する印。付けるのは build_body が
      「置き場のパスを載せた」か「返信そのものが既に届いている」枝を通った時だけ=
      本文に **問い直せ が入らない便**に限る(=受け手に手番が無いことが構造で決まる)。
      「問い直せ」の便には付けない= 受け手に手番があるから、今までどおり必ず表へ出る。
      ★この印は**受け手が畳んでよいかの判断材料**でしかない。受け手側は
        送り主+経路+audience+この印がすべて一致した時だけ畳む=片側の印だけでは沈黙しない。
    """
    fd, path = tempfile.mkstemp(suffix=".md", prefix="completion_notify_", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        cmd = [sys.executable, DISPATCH, "--dept", to_dept, "--from-dept", from_dept,
               "--from", AUTO_SENDER, "--audience", "ai", "--direct",
               "--body-file", path]
        if quiet_ok:
            cmd.append("--quiet-ack-ok")
        if dry_run:
            cmd.append("--dry-run")
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, out.strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="判定だけ・投函も追記もしない")
    ap.add_argument("--min-age-min", type=int, default=15,
                   help="完遂からこの分数は待つ(請けた側が自分で返す猶予・既定15分)")
    ap.add_argument("--since-hours", type=int, default=24,
                   help="この時間より古い完遂は触らない(既定24時間)")
    ap.add_argument("--limit", type=int, default=5,
                   help="1回に鳴らす上限(暴走の頭を押さえる・既定5)")
    ap.add_argument("--verbose", action="store_true",
                   help="鳴らせなかった件も全部並べる(既定は先頭数件だけ=常駐ログを埋めない)")
    a = ap.parse_args()
    quiet_after = 3 if not a.verbose else 10 ** 9

    now = dt.datetime.now(JST)
    done, notified, working = load_requests()

    # ★窓で絞る。過去の完遂を全部拾うと、入れた瞬間に何百通も鳴る。
    targets = {}
    for rid, d in done.items():
        if rid in notified:
            continue
        t = parse_ts(d["ts"])
        if not t:
            continue
        age = (now - t).total_seconds()
        if age < a.min_age_min * 60 or age > a.since_hours * 3600:
            continue
        d["done_at"] = t
        targets[rid] = d

    print(f"完遂で未通知の依頼: {len(targets)}件"
          f"(窓={a.since_hours}時間 / 猶予={a.min_age_min}分 / 通知済み={len(notified)}件)")
    if not targets:
        return 0

    letters, replies = load_letters(set(targets))
    # ★C-071 着地msg_idを先に集めて、送信台帳を**1回だけ**舐める(便ごとに開かない)。
    # ★HQ-0242= 1件の返信が複数通に割れている分も全部集める(1本に絞らない)。
    bodies = load_reply_bodies({m for d in targets.values() for m in landed_ids(d["evidence"])})
    consumed = {}      # ★使った返信便の位置(1通=1件しか打ち消さない・qa-reviewer指摘)
    sent, skipped, unknown, failed, rows = 0, 0, 0, 0, []

    for rid, d in sorted(targets.items(), key=lambda kv: kv[1]["done_at"]):
        if sent >= a.limit:
            print(f"  (上限{a.limit}件に達した。残りは次の回)")
            break
        try:
            letter = letters.get(rid)
            if letter is None:
                unknown += 1
                if unknown <= quiet_after:
                    print(f"  [便が無い] req={rid} dept={d['dept']} "
                          "(discord_processed に見当たらない=Chami発など dispatch を通らない依頼)")
                continue
            # ★★復路の復路を鳴らさない(2026-09-04・鎖の切断)。
            #   実物= request_log で4段の鎖が回っていた。12:52の実依頼が13:21に完遂通知され、
            #   その通知便を受け手の部屋が「実作業の依頼」として掴んで返信→13:51に**通知の通知**が
            #   逆向きへ飛び、それをまた掴んで返信→14:21に3通目が戻ってきた。
            #   (req 1545280332243275809 → DISPATCH-aegis-gl-1788495686142 →
            #    DISPATCH-qa-reviewer-1788497486055 → DISPATCH-aegis-gl-1788499286076)
            #   通知便は `--from-dept 請けた側` を明示して出しているので、そのまま次の発注として
            #   成立してしまう= **自分の出した便が自分の入力になる**。放っておけば止まらない。
            #   → この常駐が出した便から生まれた依頼は、完遂しても通知しない。鎖は2段目で終わる。
            #   ★実依頼(人や部屋が出した便)の通知は1件も減らない= fail-open のまま。
            if (letter.get("author") or "").strip() == AUTO_SENDER:
                skipped += 1
                print(f"  [復路の復路] req={rid} dept={d['dept']} "
                      f"(この便は{AUTO_SENDER}が出したもの=鎖を切る)")
                continue
            to_dept = (letter.get("from_dept") or "").strip()
            if not to_dept or not letter.get("from_dept_explicit"):
                unknown += 1
                if unknown <= quiet_after:
                    print(f"  [発注元が無い] req={rid} dept={d['dept']} "
                          "(--from-dept が明示されていない便=宛先を推定しない)")
                continue
            if to_dept == d["dept"]:
                skipped += 1
                print(f"  [自室完結] req={rid} dept={d['dept']}")
                continue
            if already_replied(replies, to_dept, d["dept"], d["done_at"], consumed):
                skipped += 1
                print(f"  [請けた側が返済み] req={rid} {d['dept']} → {to_dept}")
                continue

            landed = landed_msg(d["evidence"])
            # ★C-071 返信の本文から置き場を1本拾う。送信台帳が先・部屋の直近が控え。
            # ★★HQ-0242= **全ブロックの本文を繋いでから探す**(どれか1通に在れば足りる)。
            #   採る1本を選ぶ設計にはしない= 実物3件はどれも「長い答え+短い相槌」の2通で、
            #   **両方合わせて1件の返信**だった。選んだ時点で片方を捨てている。
            src = "send_audit"
            parts = [bodies[m] for m in landed_ids(d["evidence"]) if bodies.get(m)]
            text = "\n\n".join(parts)
            if len(parts) > 1:
                src = f"send_audit×{len(parts)}通"
            if not text:
                text, src = recent_reply(d["dept"], rid), "recent"
            spot = find_spot(text)
            # ★完遂**より後**に立った `<<WIP>>` だけを警告に使う(前のは正常な途中経過)。
            wip_ts = working.get(rid, "")
            if wip_ts:
                wt = parse_ts(wip_ts)
                if not wt or wt < d["done_at"]:
                    wip_ts = ""
            body = build_body(rid, d["dept"], letter, d, landed, spot, bool(text), wip_ts)
            # ★手番ゼロの宣言は build_body と**同じ条件**で立てる(枝が1つしか無い形にする)。
            #   置き場を載せた / 返信そのものが届いている= 受け手に頼むことが無い便。
            #   どちらでもない便は「請けた部門へ問い直せ」と書いてある=手番が有るので付けない。
            # ★WIPが立っている便は、実データ由来の例外(to_dept=hq)以外は畳んでよい
            #   (wip_fold_ok・2026-09-13 デブライネ指摘 msg=1548697831382978773)。
            quiet = wip_fold_ok(
                quiet_ack_ok(spot, bool(text), landed, d.get("state")), wip_ts, to_dept)
            ok, out = send(to_dept, d["dept"], body, a.dry_run, quiet)
            if ok:
                sent += 1
                print(f"  ★[通知] req={rid} {d['dept']} → {to_dept}"
                      f"{(' 置き場=' + spot) if spot else ' 置き場=(拾えず)'}"
                      f"{' (dry-run)' if a.dry_run else ''}")
                rows.append({"ts": now.strftime("%Y-%m-%dT%H:%M:%S"), "request_id": rid,
                             "dept": d["dept"], "state": NOTIFIED_STATE,
                             "evidence": f"完遂を発注元へ自動通知 to_dept={to_dept} "
                                         f"landed={landed or '(無し)'} "
                                         f"spot={spot or '(無し)'}/{src if text else '本文なし'} "
                                         f"wip={wip_ts or '(無し)'} "
                                         f"via=completion_notify"})
            else:
                failed += 1
                print(f"  [投函に失敗] req={rid} → {to_dept}: {out[:200]}")
        except Exception as e:
            # ★1件の事故で他を巻き込まない(fail-open)。
            failed += 1
            print(f"  [例外] req={rid}: {type(e).__name__}: {e}")

    if unknown > quiet_after:
        print(f"  (…ほか {unknown - quiet_after}件も発注元が取れない。全部見るなら --verbose)")
    print(f"\n通知 {sent} / 抑制 {skipped} / 発注元不明 {unknown} / 失敗 {failed}")
    if a.dry_run:
        print("(--dry-run なので投函も追記もしていない)")
        return 0
    if rows:
        try:
            with open(REQUEST_LOG, "a", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"request_log へ {len(rows)}行 追記した(既存行は書き換えていない)")
        except Exception as e:
            # ★ここで落ちると同じ依頼で二度鳴る。鳴ってしまった事実は消せないので声を上げる。
            print(f"★追記に失敗した= 次回このIDでもう一度鳴る恐れがある: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:      # ★常駐が他を巻き込んで止まらないように、最後も握る。
        print(f"★completion_notify が落ちた(他には波及しない): {type(e).__name__}: {e}")
        sys.exit(0)
