#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""reaction_watch — Chamiが投稿に付けたスタンプを毎朝拾い、その部屋へ手を打たせる。

★なぜ作ったか(Chami原文 2026-07-29):
  「絵文字スタンプで俺が要注意 みたいな絵文字スタンプをつけたとする。毎日朝8時に前日に新しく
   つけられたその絵文字スタンプの内容を注意深く改善する行動をとるようにして欲しい。
   こういう仕組みってできたりする? 例えば何回言っても反映されなかったり、またか…って内容は
   こっちからアラートつけるよって話」

★仕様確定(Chami原文 2026-07-29・同日中に確定):
  「❤️はなんかミスって推してるから無視で。<:saihatsu:1531748428827201772> スタンプ作った。
   これで固定するからよろしく」

★同日にもう1枚(Chami原文 2026-07-29):
  「ちなみにこちらの要望を思ったより良くしてくれたりナイスな時は
   <:golazo:1531756076154753195> ゴラッソスタンプをつけておくよ、
   **粗探しばかりすると組織の指揮(士気)が落ちる**。だよね?コーチ。」

  = **拾うのは WATCH に載せた2枚だけ**(`saihatsu` / `golazo`)。他の絵文字は全部無視(❤️含む)。
    **再発 = 「何をやめるか」/ ゴラッソ = 「何を繰り返すか」。まったく別物として扱う。**
    ゴラッソに「直せ」と言わない。改善提案部門でも Z1(再依頼)へ数えない。
  ★経緯: 当初は「好きな絵文字を付けてよい(Chamiに設定させない)」設計だった。初回巡回で過去14日を
    実測したところ人が押した絵文字は1件だけで、それが ❤️(好意)だったため
    「合図の意味を決め打ちするな」と分岐させていた。**Chamiが専用スタンプを作って意味を決めた**ので
    その前提が消え、分岐も消した。今は WATCH の kind ごとに指示文を出し分けている。

仕組み:
  1. 直近24時間の全部屋の投稿を1部屋1回のAPIで取る(after=スノーフレーク)。
  2. リアクションのうち **WATCH に載っているものだけ**を拾う(許可制)。それ以外は全部無視。
     ★照合は **ID優先**。名前だけで見ると、将来同名の別絵文字が作られた時に誤爆する。
  3. 拾った候補だけ `GET /channels/{ch}/messages/{msg}/reactions/{emoji}` で**押した人を実引き**する。
     ★`me: false`(=botが押していない)だけでは「人が押した」証明にならない。他のbotが押している
       可能性があるため、**非botのユーザーが1人でも居ること**を条件にする。
       候補は普段ごく少数なので、この実引きは呼び出し数をほとんど増やさない(必要な時だけ)。
  4. 新しいものだけを、その部屋の便として dispatch.py で投函する。
     ★Chamiの部屋(hq)へは出さない。Chamiは自分で付けたのだから報告は要らない。
  5. 改善提案部門(kaizen-analyst)へ、その日の全部屋ぶんの一覧を1本渡す。
     ★あそこは「同じことを何回言わせたか」を数える部門(KPI Z1)。
       `再発` は**苦情の合図だと確定している**ので、迷わずZ1へ数えさせる。
       `ゴラッソ` は**苦情ではない**ので Z1 へ数えさせない。見出しを分けて
       「**良かった型**」として集めさせ、他部門へ広げる材料にする。

★冪等: 拾ったものは local/llm/reaction_seen.jsonl(追記のみ)に残す。2回流しても二度投函しない。
★常駐(デーモン)は作らない。スケジュールタスク + このスクリプト1本で足りる。

★分かっていない事(誤魔化さずに書く):
  DiscordのREST APIは **リアクションが押された時刻を返さない**(メッセージの投稿時刻は返す)。
  よって「いつ付いたか」は**巡回で最初に見つけた時刻**を出す。毎朝1回走る前提なので
  「前回の巡回以降に新しく付いたもの」= Chamiの言う「前日に新しくつけられた」と一致する。

使い方:
  python scripts/discord/reaction_watch.py --dry-run     # 中身を出すだけ(投函しない・台帳も汚さない)
  python scripts/discord/reaction_watch.py               # 本番(投函して台帳へ記録)
  python scripts/discord/reaction_watch.py --hours 48    # 遡る時間を変える(既定24)
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))          # = 5SecMovieMaker
SOUGOU = os.path.normpath(os.path.join(ROOT, ".."))              # = D:\SougouStartFolder
LOCAL = os.path.join(ROOT, "local")
REGISTRY = os.path.join(SOUGOU, "00_AI-HQ", "org_registry.yml")
CHANNELS_JSON = os.path.join(LOCAL, "discord_channels.json")     # registryからの派生物(退避用)
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
LEDGER = os.path.join(LOCAL, "llm", "reaction_seen.jsonl")
# ★実時間の一報だけの台帳(2026-08-24 イージス研究室)。**朝の巡回とは別の器**にする。
#   同じ器にすると、実時間で拾った改悪が朝の巡回から見えなくなり、
#   改善提案部門が読む一覧(KAIZEN_DIGEST)から**その日の改悪が丸ごと落ちる**=数え落とし。
#   → 実時間の一報は自分の台帳で冪等を取り、朝の巡回の材料は1件も食わない。
#   ★★**この台帳は「配達の冪等」専用。集計に使うな**(研究室HQ裁定 C-056追記・2026-08-24)。
#     数える正本は**朝の一覧(KAIZEN_DIGEST)だけ**。ここを集計に足すと同じ改悪が2件に増える。
#     ★同じ改悪が部屋へ2回届くのは仕様(早鐘+朝の正式便)。2回目を「再送事故」と読むな。
REALTIME_LEDGER = os.path.join(LOCAL, "llm", "reaction_realtime_seen.jsonl")
BODY_DIR = os.path.join(LOCAL, "llm")
API = "https://discord.com/api/v10"
UA = "go5-org-reaction-watch (personal, v1)"

SENDER = "絵文字監視(毎朝8時の自動巡回)"
SKIP_DEPTS = {"hq"}          # ★Chamiの部屋。自分で付けたのだから報告は要らない
KAIZEN_DEPT = "kaizen-analyst"
# ★2026-08-23 手2(研究室HQ msg 1540947756045312121): 全部屋一覧は「傾向を見るための一覧」で
#   **その場で部門を起こす必要が無い**。起こすのを1つ止める= 実測平均 約1,600万/日 が消える。
#   → 一覧はここへ**ファイルで落とす**。改善提案部門は毎朝8:10の自分の便の中でこれを読む
#     (run_kaizen_daily_repair.py が取り込む)。★止めるのは一覧の配達だけ= 個別便(🔥の本体)は
#     1件も削っていない(上の send(dept,...) はそのまま)。
KAIZEN_DIGEST = os.path.join(LOCAL, "_work", "reaction_watch_kaizen_digest.md")
CHAMI_USER_ID = "490925528367497227"   # chami_fusoh(実測 2026-07-29)。判定の補助であって条件ではない
DISCORD_EPOCH = 1420070400000

# ★拾う絵文字の一覧(許可制)。ここに無いものは全部無視する。
#   Chamiがスタンプを増やしたら **この表へ1行足すだけ**。他は何も直さなくてよい。
#   id      = Discordのカスタム絵文字ID。★照合はこれが主(名前だけだと同名の別絵文字で誤爆する)
#             ★Unicodeの絵文字(🔥等)はIDを持たない。その時は空にして name に**絵文字そのもの**を書く
#   name    = 絵文字名。IDと**両方**一致することを確かめる(取り違えの検出用)
#   label   = 部門への本文に出す日本語の呼び名
#   meaning = その印が何の合図か。Chamiが意味を決めたものだけをここへ書く
#   kind    = 指示文(ORDERS)と改善提案部門での集計の分け方の鍵。★ここが違えば扱いも全部違う
WATCH = [
    # ★2026-08-12 追加。Chami原文=「🔥 このスタンプ絵文字は重大炎上案件/インシデント/
    #   恒久対策しろ(Chami💢)の時に使います。改善提案部門に拾ってもらいましょ」(msg 1536772116161101945)。
    #   ★このサーバーに🔥のカスタム絵文字は無い(実測 2026-08-12・ギルドの絵文字16個を全部引いた)
    #   =Chamiが押すのは**Unicodeの🔥**。だからIDは空で、name に絵文字そのものを置いて照合する。
    #   ★もし後からカスタムの🔥を作ったら、この下にID付きで**もう1行足す**(この行は消さない)。
    {"id": "", "name": "🔥", "label": "炎上", "kind": "enjo",
     "meaning": "重大炎上案件・インシデント。**恒久対策しろ**という合図(Chamiが2026-08-12に意味を確定)"},
    {"id": "1531748428827201772", "name": "saihatsu", "label": "再発", "kind": "saihatsu",
     "meaning": "同じことがまた起きた(Chamiが2026-07-29に作成・意味を確定)"},
    {"id": "1531756076154753195", "name": "golazo", "label": "ゴラッソ", "kind": "golazo",
     "meaning": "要望より良い物が出てきた・見事だった(Chamiが2026-07-29に作成・意味を確定)"},
    # ★2026-08-23 追加。Chami原文=「改悪スタンプを作った。意図としては以前は問題なく機能していた
    #   ものが、システムや作りがちょっと変わったために以前と同じ挙動ができなくなったことを指すもの。
    #   これは他と違ってすぐ認識して欲しい+翌日に再発などと同じように振り返って欲しい内容」
    #   (msg 1541111145086197770)。★炎上に次ぐ重さ=再発より前に出す(すぐ認識+翌日振り返り)。
    {"id": "1541110670748156014", "name": "kaiaku", "label": "改悪", "kind": "kaiaku",
     "meaning": "以前は問題なく機能していたのに、システムや作りが変わったせいで同じ挙動ができなくなった"
                "=変更が生んだ後退(Chamiが2026-08-23に作成・意味を確定)。★すぐ認識+翌日振り返り"},
]
WATCH_BY_ID = {w["id"]: w for w in WATCH if w["id"]}
WATCH_BY_CHAR = {w["name"]: w for w in WATCH if not w["id"]}     # Unicode絵文字はこちらで照合

# ★2枚のスタンプは **まったく別物** として扱う(2026-07-29 Chamiがゴラッソを追加した時のHQ指示)。
#   再発  = 「何をやめるか」を教える合図。直させる。
#   ゴラッソ= 「**何を繰り返すか**」を教える合図。**直せとは言わない。**
#   ★Chami原文=「粗探しばかりすると組織の指揮(士気)が落ちる。だよね?コーチ。」
#     片方だけの仕組みにすると、この組織は「怒られた記録」しか持たないことになる。
# ★2026-08-12 に3枚目(炎上🔥)が増えた。炎上は再発より強い= **恒久対策まで行け**という合図。
KIND_ORDER = ["enjo", "kaiaku", "saihatsu", "golazo"]   # 本文に出す順(重い知らせを先、良い知らせを後)。改悪=炎上の次(即認識)
KIND_LABEL = {w["kind"]: w["label"] for w in WATCH}

# 1リアクションあたり実引きする押し手の上限。Chamiが押したかを見るだけなので少なくてよい
REACTION_USER_LIMIT = 25
# 1部屋あたり1回で取るメッセージ数(APIの上限が100)。超える分は fetch_since が続きを取りに行く
MSG_LIMIT = 100
# 1部屋あたりの取得回数の上限。500件/日を超える部屋は無い(実測 最大でも数十)が、暴走は止める
MAX_PAGES = 5
# 本文に載せる原文の長さ。長すぎると部屋が読みにくくなる(原文のままだが尻を切る場合は明示する)
QUOTE_MAX = 600


# ---------------------------------------------------------------- 機械の印

def machine_marks():
    """機械が押した印の名前一式を react.py から読む(★写経しない)。

    react.py = 3段印+即答の正本。ALIAS(呼び名→実名)と FALLBACK(サーバー絵文字未登録時の代用)の
    両方を集める。片方だけ増えたときに取りこぼさないよう、必ず import して読む。

    ★許可制(WATCH)にした今、除外はこの表に頼っていない。残してあるのは2つの用途のため:
      ① 巡回の内訳を数えて「機械の印がちゃんと除外されている」と実測で言えるようにする
      ② WATCH に機械の印を誤って登録した時に**起動時に気づけるようにする**(下の watch_conflicts)
    """
    sys.path.insert(0, HERE)
    import react                      # noqa: E402  (同ディレクトリの react.py)
    names = set(react.FALLBACK.keys()) | set(react.FALLBACK.values())
    for k, vs in react.ALIAS.items():
        names.add(k)
        names.update(vs)
    return names


def watch_conflicts(marks):
    """WATCH に機械の印が紛れていないか。紛れていたら自分の印で自分を呼ぶ無限ループになる。"""
    return [w["name"] for w in WATCH if w["name"] in marks]


def watched(emo):
    """このリアクションが「拾う対象」か。★IDで照合する(名前だけだと同名の別絵文字で誤爆する)。

    戻り値= WATCH の該当行(拾う) または None(無視)。
    IDが一致して名前が違う場合は、絵文字が改名されただけなので**拾う**(IDが正)。
    ★Unicode絵文字(🔥・❤️等)はIDを持たない= **絵文字そのもの**で照合する(WATCH_BY_CHAR)。
      表に無いUnicode(❤️等の「ミスって押した」)は今までどおり全部無視される。
    """
    eid = str(emo.get("id") or "")
    if eid:
        return WATCH_BY_ID.get(eid)
    return WATCH_BY_CHAR.get(str(emo.get("name") or ""))


# ★実時間で部屋を起こす種類(2026-08-24 イージス研究室・研究室HQ DISPATCH-aegis-gl-1787500634078)。
#   Chami原文(改悪)=「**他と違ってすぐ認識して欲しい**」。だから改悪だけを実時間へ回す。
#   ★4種類を全部実時間にすると、ゴラッソでも夜中に部屋が起きる= 常に鳴る安全網は無視される(§3)。
#   ★増やすならここへ kind を1つ足すだけ。**絵文字IDは絶対にここへ書かない**(上のWATCHが正本)。
REALTIME_KINDS = ("kaiaku",)


def realtime_kind(emo):
    """このリアクションは「実時間で部屋を起こす」対象か。対象なら kind、違えば None。

    ★判定は WATCH(正本)を通す= gateway 側に絵文字IDを二度書きしないための唯一の入口。
      gateway はこの関数を呼ぶだけで、スタンプの意味を一切知らない。
    """
    hit = watched(emo)
    if not hit or hit.get("kind") not in REALTIME_KINDS:
        return None
    return hit["kind"]


# ---------------------------------------------------------------- Discord API

class Api:
    """必要最小限の呼び出しでDiscordを叩く。★レート制限に当たったら黙って落とさない。"""

    def __init__(self, token):
        self.token = token
        self.calls = 0
        self.rate_limited = 0
        self.errors = []            # (path, 理由) ★握り潰さずに最後にまとめて出す

    def get(self, path):
        req = urllib.request.Request(
            API + path, headers={"Authorization": "Bot " + self.token, "User-Agent": UA})
        for attempt in range(4):
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=25) as r:
                    body = r.read().decode("utf-8")
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    self.rate_limited += 1
                    try:
                        wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 1))
                    except Exception:
                        wait = 1.0
                    wait = min(max(wait, 0.5), 15) + 0.3 * (attempt + 1)
                    print(f"  ★レート制限。{wait:.1f}秒待って再試行({attempt + 1}/4) {path}")
                    time.sleep(wait)
                    continue
                self.errors.append((path, f"HTTP {e.code}"))
                return None
            except Exception as ex:
                self.errors.append((path, f"{type(ex).__name__}: {ex}"))
                return None
        self.errors.append((path, "レート制限で4回とも失敗"))
        return None


def read_token():
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8") as f:
        return f.read().strip()


def load_channels():
    """部屋の一覧は org_registry.yml の channels が正本(派生物のjsonは退避用)。"""
    try:
        import yaml
        with open(REGISTRY, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        chans = [c for c in (data.get("channels") or []) if c.get("id")]
        if chans:
            return chans, "org_registry.yml"
    except Exception as e:
        print(f"★org_registry.yml を読めない({type(e).__name__}: {e})。派生物のjsonへ退避する")
    with open(CHANNELS_JSON, encoding="utf-8") as f:
        return json.load(f), "discord_channels.json(派生物)"


def emoji_key(emo):
    """API用の絵文字キー。カスタム絵文字は name:id、Unicodeはそのまま。"""
    return f"{emo.get('name')}:{emo['id']}" if emo.get("id") else str(emo.get("name") or "")


# ---------------------------------------------------------------- 台帳(冪等)

def load_ledger(path=None):
    path = path or LEDGER
    seen = set()
    if not os.path.exists(path):
        return seen
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["key"])
            except Exception:
                continue        # 壊れた行で全体を止めない
    return seen


def ledger_rows(items, posted):
    """台帳へ書く行= **行き先すべてへ届いたものだけ**(重複は畳む)。

    ★朝の巡回と実時間の一報が同じ判定を使う(判定を2箇所に置かない・§3)。
      届かなかったものは書かない= 次回もう一度拾い直す(合図を落とさない)。
    """
    delivered = ({it["key"] for it in posted}
                 | {it["key"] for it in items if it["dept"] in SKIP_DEPTS})
    uniq, keys = [], set()
    for it in items:
        if it["key"] not in delivered or it["key"] in keys:
            continue
        keys.add(it["key"])
        uniq.append({k: it[k] for k in
                     ("key", "dept", "channel", "msg_id", "emoji", "by", "by_chami", "detected_at")})
    return uniq


def append_ledger(rows, path=None):
    path = path or LEDGER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 収集

def fetch_since(api, cid, snowflake, truncated):
    """その部屋の、指定時刻以降の投稿を**全部**取る(足りなければ続きを取りに行く)。

    ★2026-07-29に実測で見つけた穴。`after=` を付けると Discord は
      **「その時刻より後の古い方から」limit件**を返す(新しい方からではない)。
      よって1部屋が期間内に limit件を超えると、**新しい方が丸ごと落ちる**。
      再発スタンプは普通「さっきの投稿」に付くので、**一番落としてはいけない所が落ちる**。
      実際、14日で試した時に system-engineer の投稿が100件で頭打ちになり、
      24時間で拾えていた再発スタンプが**0件になった**(=取りこぼしを実物で確認した)。
    → 最後に取ったIDを次の after にして、返りが limit未満になるまで続ける。
      普段の1日は1部屋あたり1回で終わるので、呼び出し数はほぼ増えない。
    """
    out, cursor = [], snowflake
    for _ in range(MAX_PAGES):
        page = api.get(f"/channels/{cid}/messages?limit={MSG_LIMIT}&after={cursor}")
        if page is None:
            return out if out else None      # 途中で落ちた分は api.errors に積んである
        page.sort(key=lambda m: int(m["id"]))    # 古い順に揃える(APIの並びに依存しない)
        out.extend(page)
        if len(page) < MSG_LIMIT:
            return out                        # 取り切った
        cursor = page[-1]["id"]
        time.sleep(0.15)
    truncated.append(cid)                     # ★上限に当たった=まだ残っている。黙って落とさない
    return out


def collect(api, chans, since_ms, marks, seen, now_str):
    """新しく付いた `再発` スタンプだけを集めて返す。"""
    snowflake = (since_ms - DISCORD_EPOCH) << 22
    found, scanned, with_reaction = [], 0, 0
    skipped_machine = skipped_other = skipped_bot = 0
    truncated = []
    for ch in chans:
        cid = str(ch["id"])
        msgs = fetch_since(api, cid, snowflake, truncated)
        if msgs is None:
            continue            # 失敗は api.errors に積んである。最後に必ず出す
        scanned += len(msgs)
        for m in msgs:
            reactions = m.get("reactions") or []
            if not reactions:
                continue
            with_reaction += 1
            for r in reactions:
                emo = r.get("emoji") or {}
                hit = watched(emo)
                if not hit:
                    # ★許可制。WATCH に無いものは全部無視する(❤️等の「ミスって押した」も含む)。
                    #   内訳だけ分けて数えておく(機械の印が除外できている実測を出すため)。
                    if str(emo.get("name") or "") in marks:
                        skipped_machine += 1
                    else:
                        skipped_other += 1
                    continue
                key = f"{cid}:{m['id']}:{emoji_key(emo)}"
                if key in seen:
                    continue                      # ★一度拾ったものは二度拾わない
                # ここまで来たものだけ「誰が押したか」を実引きする(呼び出し数を増やさないため)
                users = api.get(
                    f"/channels/{cid}/messages/{m['id']}/reactions/"
                    f"{urllib.parse.quote(emoji_key(emo))}?limit={REACTION_USER_LIMIT}")
                humans = [u for u in (users or []) if not u.get("bot")]
                if not humans:
                    skipped_bot += 1
                    continue                      # botが押した絵文字。Chamiの合図ではない
                found.append({
                    "key": key,
                    "dept": ch.get("dept", ""),
                    "channel": ch.get("name", ""),
                    "channel_id": cid,
                    "msg_id": str(m["id"]),
                    # ★Unicodeは `:🔥:` と書くと壊れて見えるので、絵文字そのものを出す
                    "emoji": (f"{hit['label']} :{hit['name']}:" if hit["id"]
                              else f"{hit['label']} {hit['name']}"),
                    "kind": hit["kind"],
                    "meaning": hit["meaning"],
                    "author": (m.get("author") or {}).get("username", ""),
                    "posted_at": str(m.get("timestamp") or ""),
                    "content": (m.get("content") or ""),
                    "by": [f"{u.get('username')}({u.get('id')})" for u in humans],
                    "by_chami": any(str(u.get("id")) == CHAMI_USER_ID for u in humans),
                    "detected_at": now_str,
                })
                time.sleep(0.2)   # 実引きは連打しない(レート制限に当たりにくくする)
        time.sleep(0.15)
    return found, {"scanned": scanned, "with_reaction": with_reaction,
                   "skipped_machine": skipped_machine, "skipped_other": skipped_other,
                   "skipped_bot": skipped_bot, "truncated": truncated}


# ---------------------------------------------------------------- 本文

def quote_body(text):
    text = (text or "").strip()
    if not text:
        return "(本文なし。画像か添付だけの投稿)"
    if len(text) > QUOTE_MAX:
        return text[:QUOTE_MAX] + f"\n…(原文はここで切っています。全文は元投稿を見ること・全{len(text)}字)"
    return text


def jump_url(guild_id, cid, mid):
    return f"https://discord.com/channels/{guild_id or '@me'}/{cid}/{mid}"


def item_block(it, guild_id, n=None):
    head = f"{n}. " if n else ""
    who = "Chami" if it["by_chami"] else "／".join(it["by"])
    return (
        f"{head}【{it['emoji']}】{who} が付けた\n"
        f"   部屋: {it['channel']} (dept={it['dept']})\n"
        f"   投稿: {jump_url(guild_id, it['channel_id'], it['msg_id'])}  (msg_id={it['msg_id']})\n"
        f"   投稿者: {it['author']} / 投稿時刻: {it['posted_at']}\n"
        f"   検知: {it['detected_at']} ★DiscordのAPIは「絵文字を押した時刻」を返さない。"
        f"これは巡回で最初に見つけた時刻(=前回の巡回以降に付いた、という意味)\n"
        f"   ----- 投稿の本文(原文のまま) -----\n"
        f"{quote_body(it['content'])}\n"
        f"   ----------------------------------\n"
    )


# ★意味はChamiが決めた(2026-07-29「これで固定するからよろしく」)ので、決め打ちで強く出してよい。
#   一時期あった①②③の「何の合図かを読み取れ」という分岐は、専用スタンプの新設で不要になったので消した。
# ★2枚は**まったく別の指示文**にする。同じ枠で「良かったですね、では直しましょう」とやると、
#   ゴラッソが再発の亜種に見えてしまい、**何を繰り返すべきかが伝わらない**。
ORDERS = {
    "enjo": (
        "★これは Chami が **🔥(炎上)** のスタンプを付けた投稿だ= **重大炎上案件・インシデント**の合図。\n"
        "  ★再発より強い。**恒久対策まで行けとはっきり言われている**(Chami原文 2026-08-12=\n"
        "   「重大炎上案件/インシデント/恒久対策しろ(Chami💢)の時に使います」)。\n"
        "  ①**その場の止血を先に打て**(共通規律C-033)。壊れたまま夜を越すな。\n"
        "  ②**真因を機構で書け。**『気をつける』『次から確認する』は対策ではない。\n"
        "  ③**恒久対策を実装まで持っていけ**(C-038)。その場でなくてよいが、**必ず実装まで行く**。\n"
        "  ④終わっていないなら**何が残っているかを普通の言葉で書け**(共通規律§4.55)。\n"
        "★『入れた』と『直った』を混ぜるな。**同じ場面で実物を見るまで直ったと言うな。**\n"),
    "kaiaku": (
        "★これは Chami が **`改悪`** のスタンプを付けた投稿だ= **以前は動いていたのに、システムや作りが\n"
        "  変わったせいで同じ挙動ができなくなった=変更が生んだ後退**の合図(Chami原文 2026-08-23=\n"
        "   「以前は問題なく機能していたものが、システムや作りがちょっと変わったために以前と同じ挙動が\n"
        "    できなくなったことを指す。他と違ってすぐ認識して欲しい+翌日に振り返って欲しい」)。\n"
        "  ①**まず『前は動いていた』を実物で確かめろ**(壊れる前の挙動=比較対象。共通規律§4.55の0歩目)。\n"
        "  ②**何の変更が壊したかを特定しろ。**どのcommit/リファクタ/仕様変更が後退を入れたか(再発とは別=\n"
        "    『同じ依頼の繰り返し』ではなく『前は出来ていた事が変更で消えた』)。\n"
        "  ③**挙動を戻せ。** 戻せないなら何が要るかを1行で書け。\n"
        "  ④★**回帰ガードを付けろ**=同じ種類の変更でまた黙って壊れない検査(C-038・C-053)。\n"
        "    改悪の恒久対策は『気をつける』ではなく『次の変更で壊れたら赤くなる検査』だ。\n"
        "★『入れた』と『直った』を混ぜるな。**壊れていた同じ場面で実物を見るまで直ったと言うな。**\n"),
    "saihatsu": (
        "★これは Chami が **`再発`** のスタンプを付けた投稿だ= **同じことがまた起きた**という合図。\n"
        "  ①**何が繰り返されているのか**を実物で確かめろ(過去にいつ同じことがあったかも探せ)。\n"
        "  ②**なぜ直っていないのか**を構造で書け(『気をつけます』で終わらせるな)。\n"
        "  ③直せ。直せないなら**何が要るか**を1行で書け。\n"
        "★『入れた』と『直った』を混ぜるな(共通規律§4.55)。実物で確かめてから直ったと言え。\n"
    ),
    "golazo": (
        "★これは Chami が **`ゴラッソ`** のスタンプを付けた投稿だ= **要望より良い物が出た**という合図。\n"
        "  ★**直せとは言われていない。** ここで直しに行くな。ここは**何を繰り返すか**を決める場だ。\n"
        "  ①**なぜ良かったのかを、実物から具体で書け。**\n"
        "    『丁寧だった』のような感想で終わらせるな。**何をどう判断し、何を先回りしたのか**を、\n"
        "    次の人がそれを読んで**同じことをやれる形**で書け。\n"
        "  ②それは**他の部屋でも使える形か**を判断しろ。使えるなら**共通規律§3.9の経路でHQへ渡せ**。\n"
        "  ③**自分の部屋の作法として残せ。** 次に同じ場面が来た時、同じ質で出せるようにするため。\n"
        "★**謙遜で終わらせるな。**『たまたまです』は、**次に再現できない**という意味になる。\n"
    ),
}


def group_by_kind(items):
    """スタンプの種類ごとに分ける。★再発とゴラッソを混ぜない(混ぜると扱いが伝わらない)。"""
    out = {}
    for it in items:
        out.setdefault(it["kind"], []).append(it)
    return [(k, out[k]) for k in KIND_ORDER if k in out]


HEADING = {
    "enjo": "■ Chamiが 🔥(炎上) スタンプを付けた投稿がこの部屋にある(毎朝8時の自動巡回)。★最優先。",
    "kaiaku": "■ Chamiが `改悪`(変更起因の後退) スタンプを付けた投稿がこの部屋にある。★以前は動いていたのに作りが変わって壊れた=即認識+翌日振り返り。",
    "saihatsu": "■ Chamiが `再発` スタンプを付けた投稿がこの部屋にある(毎朝8時の自動巡回)。",
    "golazo": "■ Chamiが `ゴラッソ` スタンプを付けた投稿がこの部屋にある(毎朝8時の自動巡回)。",
}

WHY = (
    "★なぜこの便が来るのか(Chami原文 2026-07-29):\n"
    "  「絵文字スタンプで俺が要注意 みたいな絵文字スタンプをつけたとする。毎日朝8時に前日に\n"
    "   新しくつけられたその絵文字スタンプの内容を注意深く改善する行動をとるようにして欲しい。\n"
    "   例えば何回言っても反映されなかったり、またか…って内容はこっちからアラートつけるよって話」\n"
    "  同日に専用スタンプが2枚作られ、意味が固定された(Chami原文):\n"
    "  「<:saihatsu:1531748428827201772> スタンプ作った。これで固定するからよろしく」\n"
    "  「こちらの要望を思ったより良くしてくれたりナイスな時は <:golazo:1531756076154753195>\n"
    "   ゴラッソスタンプをつけておくよ、**粗探しばかりすると組織の指揮(士気)が落ちる**。だよね?コーチ。」\n"
    "  = **再発は「何をやめるか」、ゴラッソは「何を繰り返すか」**の合図。別物として扱うこと。\n"
    "  ★2026-08-12に3枚目が増えた(Chami原文):\n"
    "  「🔥 このスタンプ絵文字は重大炎上案件/インシデント/恒久対策しろ(Chami💢)の時に使います。\n"
    "   改善提案部門に拾ってもらいましょ」\n"
    "  = **炎上は再発より重い。** 「またか」ではなく「**これは事故だ。恒久対策まで行け**」。\n"
    "  ★2026-08-23に4枚目が増えた(Chami原文 msg 1541111145086197770):\n"
    "  「改悪スタンプを作った。以前は問題なく機能していたものが、システムや作りがちょっと変わった\n"
    "   ために以前と同じ挙動ができなくなったことを指す。他と違ってすぐ認識して欲しい+翌日に\n"
    "   再発などと同じように振り返って欲しい」\n"
    "  = **改悪=変更起因の後退。** 再発(同じ依頼の繰り返し)とは別枠。恒久対策=**回帰ガード**。"
)


REALTIME_BANNER = (
    "■■ これは**実時間の一報**だ(スタンプが押された直後に届いている。朝8時の巡回ではない)。\n"
    "   ★同じ件は**朝8時の巡回でもう一度届く**。そちらが正式な便(一覧・集計もそちらが正)。\n"
    "   ここでは「今すぐ認識する」ことだけが要る= Chami原文「他と違ってすぐ認識して欲しい」。\n"
)


def dept_body(dept, items, guild_id, realtime=False):
    groups = group_by_kind(items)
    lines = []
    if realtime:
        lines.append(REALTIME_BANNER)
    for gi, (kind, its) in enumerate(groups):
        if gi:
            lines.append("\n" + "=" * 60 + "\n")   # ★種類の切れ目をはっきり分ける
        lines.append(HEADING[kind])
        lines.append("")
        lines.append(f"該当 {len(its)}件。")
        lines.append("")
        for i, it in enumerate(its, 1):
            lines.append(item_block(it, guild_id, i))
        lines.append(ORDERS[kind])
    lines.append(WHY)
    return "\n".join(lines)


# ★改善提案部門での扱い。**再発とゴラッソを混ぜない**(見出しを分ける・数え方も別)。
KAIZEN_SECTION = {
    "enjo": {
        "head": "◆◆ 炎上(🔥)= 重大インシデント。恒久対策しろ ◆◆",
        "note": (
            "★意味は Chami が固定した(2026-08-12 原文):\n"
            "  「🔥 このスタンプ絵文字は重大炎上案件/インシデント/恒久対策しろ(Chami💢)の時に使います。\n"
            "   改善提案部門に拾ってもらいましょ」\n"
            "  = **再発より重い。** 再発が「またか」なら、炎上は「**これは事故だ**」。\n"
            "  → **Z1(何回言わせたか)とは別に数えろ。** 炎上は回数ではなく**1件ごとに恒久対策の有無**で見る。"
        ),
        "ask": (
            "★炎上について求めるもの: **恒久対策が実装まで届いたか**を1件ずつ追うこと(C-038)。\n"
            "  ①何が起きたか(実物) ②止血は打たれたか ③**恒久対策は実装されたか、まだか**\n"
            "  ★『提案した』で閉じるな。**実装されていない炎上は、開いたままとして数え続けろ。**\n"
            "  ★週次PDCAでは「炎上の件数」ではなく「**恒久対策が入っていない炎上の件数**」を出すこと。"
        ),
    },
    "kaiaku": {
        "head": "◆◆ 改悪(`改悪`)= 変更起因の後退。前は動いていたのに作りが変わって壊れた ◆◆",
        "note": (
            "★意味は Chami が固定した(2026-08-23 原文):\n"
            "  「改悪スタンプを作った。以前は問題なく機能していたものが、システムや作りがちょっと変わった\n"
            "   ために以前と同じ挙動ができなくなったことを指す。他と違ってすぐ認識して欲しい+翌日に\n"
            "   再発などと同じように振り返って欲しい」\n"
            "  = **再発とは別物。** 再発は『同じ依頼を何回も言わせた』、改悪は『前は出来ていた事が変更で消えた』。\n"
            "  → **Z1(何回言わせたか)とは別枠で数えろ。** 改悪は**変更起因の後退**という独立の真因クラスだ。\n"
            "  → 数え方の鍵=『**どの変更(commit/リファクタ/仕様変更)が後退を入れたか**』を1件ずつ紐づける。"
        ),
        "ask": (
            "★改悪について求めるもの: **回帰(リグレッション)として1件ずつ追うこと。**\n"
            "  ①何が前は動いていたか(壊れる前の実物) ②どの変更が壊したか ③戻したか\n"
            "  ④**回帰ガードは入ったか**=同じ種類の変更でまた黙って壊れない検査(C-038・C-053)。\n"
            "  ★『直した』で閉じるな。**回帰ガードの無い改悪は、また同じ変更で再発する**=開いたまま数え続けろ。\n"
            "  ★週次PDCAでは「改悪の件数」と「**回帰ガードが入っていない改悪の件数**」を分けて出すこと。"
        ),
    },
    "saihatsu": {
        "head": "◆◆ 再発(`saihatsu`)= 同じことをまた言わせた ◆◆",
        "note": (
            "★意味は Chami が固定した(2026-07-29):\n"
            "  「<:saihatsu:1531748428827201772> スタンプ作った。これで固定するからよろしく」\n"
            "  = **同じことがまた起きた=またか**。**苦情の合図だと確定している。**\n"
            "  → **迷わず KPI Z1(同じことを何回言わせたか)へ数え込むこと。** 例外判定は要らない。\n"
            "  ★ただし 1件=1回の再依頼**ではない**。**同じ依頼への何度目か**を元投稿まで遡って判定しろ。\n"
            "    スタンプは「何度目かが1以上である」ことしか教えてくれない。回数を出すのはお前の仕事。"
        ),
        "ask": (
            "★再発について求めるもの: 同じ指摘が繰り返されている塊を見つけ、\n"
            "  ①何回目か ②なぜ毎回すり抜けるのか ③機械で止める案 を出すこと。\n"
            "  ★心がけで再発を止めない。機械で止まる形にすること。"
        ),
    },
    "golazo": {
        "head": "◆◆ ゴラッソ(`golazo`)= 要望より良い物が出た ◆◆",
        "note": (
            "★意味は Chami が固定した(2026-07-29 原文):\n"
            "  「こちらの要望を思ったより良くしてくれたりナイスな時は <:golazo:1531756076154753195>\n"
            "   ゴラッソスタンプをつけておくよ、**粗探しばかりすると組織の指揮(士気)が落ちる**。だよね?コーチ。」\n"
            "  ★**これは苦情ではない。Z1(再依頼の回数)へは絶対に数えるな。**\n"
            "  ★代わりに **「良かった型」として集めろ。** 何が起きたから良くなったのかを型にする。"
        ),
        "ask": (
            "★ゴラッソについて求めるもの: **他部門へ広げられる型**として抽出すること。\n"
            "  ①**何をしたから要望を超えたのか**(先回りの中身・判断の分かれ目を具体で)\n"
            "  ②**その型は他の部屋でも成り立つか**(その部屋固有の事情に依存していないか)\n"
            "  ③広げるなら**どの部屋のどの場面に効くか**を名指しで書け。\n"
            "  ★週次PDCAでは「**再発を減らす**」だけでなく「**ゴラッソが出た型を他部門へ広げる**」も見ること。\n"
            "    Chamiの言葉=「**粗探しばかりすると組織の士気が落ちる**」。\n"
            "    減点だけを数える改善は、この組織に「怒られた記録」しか残さない。"
        ),
    },
}


def write_kaizen_digest(kbody, count, dry_run):
    """全部屋一覧をファイルへ落とす。**書けたら True**(=行き先へ届いた)。

    ★2026-08-23 イージス研究室。手2(=一覧の配達をファイルへ替えた)には**静かな死**が残っていた。
      配達だった頃は「起こされなかった」が見えたが、ファイルは**無いことが正常な日と見分けが付かない**。
      実際、0件の日は `if not items:` で早く返るのでファイルを書かず、改善提案部門の朝の便には
      「一覧: 無し」と出る——**絵文字監視が死んでいる日と一字一句同じ**だった。
      → 0件でも必ず書く= このファイルが「毎朝必ず動く脈」になり、`local/llm/producers.json` の
        鮮度警報(absence_watchdog.check_producer_freshness)で見張れる形になる。
      ★書き口をここ1本にするのは、0件の枝と通常の枝で書式が割れないため(判定を2箇所に置かない)。
    """
    if dry_run:
        print("---8<--- ここから本文(ファイルには書かない) ---8<---")
        print(kbody)
        print("---8<--- ここまで本文 ---8<---")
        return True
    try:
        os.makedirs(os.path.dirname(KAIZEN_DIGEST), exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        header = ("<!-- 絵文字監視(毎朝8時)が書いた全部屋一覧。改善提案部門が8:10の便で読む。 -->\n"
                  f"<!-- 書込時刻: {stamp} / 件数: {count} -->\n\n")
        with open(KAIZEN_DIGEST, "w", encoding="utf-8") as f:
            f.write(header + kbody + "\n")
        print(f"   一覧を書いた: {KAIZEN_DIGEST}")
        return True
    except Exception as e:                                    # noqa: BLE001
        print(f"   ★一覧のファイル書き込みに失敗: {type(e).__name__}: {e}")
        return False


def kaizen_body(items, guild_id, stats, hours):
    groups = group_by_kind(items)
    counts = " / ".join(f"{KIND_LABEL.get(k, k)} {len(v)}件" for k, v in groups)
    lines = [
        "■ 本日ぶん: Chamiが付けたスタンプの全部屋一覧(毎朝8時の自動巡回)。",
        "",
        f"合計 {len(items)}件({counts})。"
        f"(巡回: 直近{hours}hの投稿 {stats['scanned']}件・うちリアクション付き {stats['with_reaction']}件。"
        f"機械の印 {stats['skipped_machine']}件・対象外の絵文字 {stats['skipped_other']}件は除外)",
        "",
        "★**3種類は別物だ。混ぜて数えるな。** 見出しごとに数え方も求めるものも違う。",
    ]
    for kind, its in groups:
        sec = KAIZEN_SECTION[kind]
        by_dept = {}
        for it in its:
            by_dept.setdefault(it["dept"], []).append(it)
        lines.append("\n" + "=" * 60)
        lines.append(sec["head"])
        lines.append("=" * 60 + "\n")
        lines.append(sec["note"])
        lines.append("")
        lines.append(f"該当 {len(its)}件 / {len(by_dept)}部屋。")
        lines.append("")
        n = 0
        for dept in sorted(by_dept):
            lines.append(f"--- {dept} ({len(by_dept[dept])}件) ---")
            for it in by_dept[dept]:
                n += 1
                lines.append(item_block(it, guild_id, n))
        lines.append(sec["ask"])
    return "\n".join(lines)


# ------------------------------------------- 未確認の不具合台帳へ積む(2026-07-29)
#
# ★なぜここで積むのか(改善提案部門の実測。正本=
#   00_AI-HQ/departments/kaizen/pdca/2026-07-29_saihatsu-2.md §構造指摘C):
#   > 1つのセッションがバグを『壊れた実物を見る→同じ場面で直ったを見る』(§4.55)まで
#   > 見届ける前に交代し、次のセッションは『commitに封じたと書いてある』(台帳)を継ぐが
#   > 『Chamiの画面で消える』(現物)を継がない。だから毎回『封じた/再発を封じる』を再宣言する。
#   再発スタンプは「**壊れた実物がここに在る**」という Chami 直筆の指差しだ。
#   便として部屋へ出すだけだと、その部屋のセッションが交代した瞬間に消える。
#   → **世代をまたぐ器**(local/llm/open_defects.jsonl)へも同時に積む。
#
# ★積むのは `再発`(saihatsu)と `炎上`(enjo)。ゴラッソは不具合ではない(混ぜたら意味が壊れる)。
#   ★2026-08-12 に炎上🔥を足した= 「重大インシデント/恒久対策しろ」は**まさに世代をまたいで
#     追い続けるべきもの**だ。便として部屋へ出すだけでは、そのセッションが交代した瞬間に消える。
# ★正本の実装は session_relay.py 側に1つだけ置く(判定を2箇所に置くと必ず片方が古くなる=ORG-11)。
# ★★この処理が何で失敗しても、**巡回と投函は1バイトも変えない**(沈黙を作らない)。
DEFECT_SOURCE = "reaction_watch(再発スタンプ)"
DEFECT_SOURCE_ENJO = "reaction_watch(炎上スタンプ🔥)"
DEFECT_KINDS = ("saihatsu", "enjo")     # ★台帳へ積む種類。ゴラッソは積まない


def stack_open_defects(items, guild_id, dry_run):
    """再発スタンプの付いた便を「まだ直ったと確認できていない不具合」として積む。

    戻り値 (積んだ件数, 既にあった件数, 失敗の理由 or "")。
    ★冪等= 同じ投稿から作る id は同じなので、二度流しても増えない(session_relay側で判定)。

    ★★2026-08-14(イージス研究室)= **重い方を先に積む**。
      同じ投稿にChamiが🔥と再発を**両方**押すことがある(実測 2026-08-14= 14投稿中11件)。
      台帳は msg_id で1件に畳むので、**先に処理した方のスタンプだけが source に残る**。
      並びが来た順のままだと再発が先に当たり、実測で **11件中10件から🔥が消えていた**。
      🔥は「恒久対策まで行け」= 再発より重い(C-038/C-040)。消えると重さが下がる。
      → ①KIND_ORDER(enjo が先頭)で並べ替えてから積む
        ②それでも既に再発として積まれている古い行には `mark_defect_enjo` で後から印を足す
      巡回の本文が「★3種類は別物だ。混ぜて数えるな」と言っている以上、**台帳の側でも混ぜない**。
    """
    targets = [it for it in items if it.get("kind") in DEFECT_KINDS]
    if not targets:
        return 0, 0, ""
    targets.sort(key=lambda it: KIND_ORDER.index(it.get("kind"))
                 if it.get("kind") in KIND_ORDER else len(KIND_ORDER))
    if dry_run:
        return 0, 0, "dry-run(台帳は汚さない)"
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        import session_relay
    except Exception as e:                            # noqa: BLE001
        return 0, 0, f"session_relay を読めない({type(e).__name__}: {e})"
    added = dup = upgraded = 0
    for it in targets:
        try:
            # ★「壊れた実物の在りか」= Chamiがスタンプを押した**その投稿**。
            #   ジャンプできるリンクと msg_id の両方を残す(片方が使えなくなっても辿れるように)。
            broken = (f"{jump_url(guild_id, it['channel_id'], it['msg_id'])} "
                      f"(msg_id={it['msg_id']} / 部屋={it.get('channel', '')})")
            symptom = " ".join((it.get("content") or "").split())[:600] \
                or "(投稿本文なし。画像か添付だけの投稿。元投稿を見ること)"
            # ★2026-07-29 台帳が `kind`(defect / request)を持つようになった
            #   (改善書_記憶と引き継ぎの抜本見直し §6 第1手)。
            #   **ここは常に defect**= 再発スタンプは「壊れた実物がここに在る」という指差しであって、
            #   「まだ終わっていない依頼」ではない。混ぜたら台帳の意味が壊れる。
            #   ★明示的に渡す= 既定値に頼ると、既定が変わった日に黙って意味が変わる。
            # ★どのスタンプ由来かを source に残す= 台帳を見ただけで「炎上として積まれた」と分かる
            src = DEFECT_SOURCE_ENJO if it.get("kind") == "enjo" else DEFECT_SOURCE
            _did, is_new = session_relay.open_defect(
                dept=it.get("dept", ""), symptom=symptom, broken=broken,
                noticed_at=it.get("detected_at", ""), source=src,
                kind=session_relay.DEFECT_KIND_DEFECT)
            if is_new:
                added += 1
            else:
                dup += 1
                # ★既に在る行が「再発」として積まれていて、今回の便が🔥なら**重さだけ足す**。
                #   これで過去に積まれた行も、次の巡回で自然に🔥へ上がる(取りこぼしを残さない)。
                if it.get("kind") == "enjo" and session_relay.mark_defect_enjo(
                        it.get("dept", ""), _did, where=str(it.get("msg_id", ""))):
                    upgraded += 1
        except Exception as e:                        # noqa: BLE001
            # ★1件失敗しても残りは積む。巡回そのものは絶対に止めない
            print(f"   ★未確認台帳へ積めなかった msg_id={it.get('msg_id')} "
                  f"({type(e).__name__}: {e})")
    if upgraded:
        print(f"   ★既存の {upgraded}件へ🔥(炎上)の印を足した"
              "(再発として積まれていたが、Chamiは🔥も押していた)")
    return added, dup, ""


# ---------------------------------------------------------------- 投函

def send(dept, body, dry_run, sender=None, tag=""):
    """dispatch.py でその部門へ投函する。★既存2本(se_daily_review/kaizen_round)と同じ作法。"""
    os.makedirs(BODY_DIR, exist_ok=True)
    path = os.path.join(BODY_DIR, f"reaction_watch_body_{tag}{dept}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    # ★C-050の宛先宣言(2026-08-23)= 中身はChamiが押した印(再発/炎上)そのもの。
    #   受けた部屋の返事はChamiが読む=削らせない。
    cmd = [sys.executable, DISPATCH, "--dept", dept, "--direct",
           "--from", sender or SENDER, "--audience", "chami", "--body-file", path]
    if dry_run:
        cmd.append("--dry-run")
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=120)
        out = (p.stdout or b"").decode("utf-8", "replace").strip()
        err = (p.stderr or b"").decode("utf-8", "replace").strip()
        if out:
            print("   " + out.replace("\n", "\n   "))
        if err:
            print("   [stderr] " + err.replace("\n", "\n   "))
        return p.returncode == 0
    except Exception as e:
        print(f"   ★投函に失敗 dept={dept}: {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="中身を出すだけ。投函もせず台帳も汚さない(★本投函の前に必ず1回これを見る)")
    ap.add_argument("--hours", type=int, default=24, help="遡る時間(既定24)")
    ap.add_argument("--only-kind", default="", choices=[""] + list(REALTIME_KINDS),
                    help="実時間の一報用。この種類だけを部屋へ出し、"
                         "台帳も一覧も朝の巡回とは分ける(既定=空=従来どおり朝の巡回)")
    a = ap.parse_args()

    # ★実時間モード= gateway が「改悪が押された」瞬間に呼ぶ経路(2026-08-24 イージス研究室)。
    #   朝の巡回と**共有しないもの**= ①台帳(REALTIME_LEDGER) ②一覧(書かない) ③名乗り。
    #   共有するもの= 絵文字の表・意味・指示文・本文の組み立て(=正本は1つ)。
    rt = a.only_kind or ""
    ledger_path = REALTIME_LEDGER if rt else LEDGER
    sender = (f"絵文字監視({KIND_LABEL.get(rt, rt)}スタンプの実時間検知)" if rt else SENDER)

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"===== スタンプ監視 {now_str} " + ("[dry-run]" if a.dry_run else "[本番]")
          + (f" [実時間 only-kind={rt}]" if rt else "") + " =====")

    marks = machine_marks()
    print("拾う対象(許可制・IDで照合):")
    for w in WATCH:
        how = f"id={w['id']}" if w["id"] else "id無し(Unicode絵文字そのもので照合)"
        print(f"   {w['name']} {how} 呼び名={w['label']} 意味={w['meaning']}")
    print(f"機械の印(react.pyから読取・常に対象外): {' '.join(sorted(marks))}")

    bad = watch_conflicts(marks)
    if bad:
        # ★機械の印を拾うと、自分が押した印で自分を呼び続ける。設定ミスなので止める。
        print(f"★中止: WATCH に機械の印が入っている ({', '.join(bad)})。"
              "自分の印で自分を呼ぶ無限ループになる。WATCH を直すこと。")
        return 2

    chans, src = load_channels()
    print(f"部屋 {len(chans)}室 (出典 {src}) / 遡り {a.hours}時間")

    api = Api(read_token())
    guild_id = ""
    if chans:
        info = api.get(f"/channels/{chans[0]['id']}")
        guild_id = str((info or {}).get("guild_id", "") or "")

    seen = load_ledger(ledger_path)
    print(f"台帳の既知 {len(seen)}件 ({ledger_path})")

    since_ms = int(time.time() * 1000) - a.hours * 3600 * 1000
    items, stats = collect(api, chans, since_ms, marks, seen, now_str)
    if rt:
        # ★この種類以外は**触らない**(朝の巡回の材料。ここで食うと一覧から落ちる)。
        dropped = len(items)
        items = [it for it in items if it.get("kind") == rt]
        print(f"★実時間モード: {rt} 以外の {dropped - len(items)}件は朝の巡回へ残した(台帳にも書かない)")

    print(f"\n--- 巡回結果 ---")
    print(f"直近{a.hours}hの投稿 {stats['scanned']}件 / リアクション付き {stats['with_reaction']}件")
    print(f"機械の印として除外 {stats['skipped_machine']}件 / "
          f"対象外の絵文字として除外 {stats['skipped_other']}件 / "
          f"botが押した対象スタンプとして除外 {stats['skipped_bot']}件")
    print(f"★Chami(人)が新しく付けたスタンプ: 合計 {len(items)}件")
    for kind, its in group_by_kind(items):
        print(f"   {KIND_LABEL.get(kind, kind)} ({kind}): {len(its)}件")
    print(f"API呼び出し {api.calls}回 / レート制限にあたった回数 {api.rate_limited}回")

    if stats["truncated"]:
        # ★上限まで取ってもまだ残っている=取りこぼしている可能性がある。必ず見えるようにする。
        print(f"\n★取り切れなかった部屋がある({len(stats['truncated'])}室・{MAX_PAGES}回取っても続きがある)。"
              "MAX_PAGES を上げるか遡り時間を短くすること:")
        for cid in stats["truncated"]:
            name = next((c.get("name") for c in chans if str(c["id"]) == cid), cid)
            print(f"   {name} ({cid})")

    if api.errors:
        print(f"\n★取れなかった部屋がある({len(api.errors)}件)。黙って落とさない:")
        for p, why in api.errors[:20]:
            print(f"   {why}  {p}")

    if not items:
        print("\n新しく付いたスタンプは 0件。投函するものは無い。")
        if rt:
            # ★実時間モードでは一覧を書かない= 朝の脈(KAIZEN_DIGEST)を別の手で更新しない(C-054)。
            #   ここで書くと「毎朝8時に書かれる」という鮮度警報の前提が崩れる。
            return 1 if api.errors else 0
        # ★0件でも一覧は書く(2026-08-23 イージス研究室)。書かないと「0件の朝」と
        #   「絵文字監視が死んだ朝」が改善提案部門から**同じ「無し」に見える**。
        #   ファイルを毎朝必ず動く脈にして、producers.json の鮮度警報で死を捕まえる。
        write_kaizen_digest("(本日は新しく付いたスタンプが 0件。巡回そのものは正常に終わっている)",
                            0, a.dry_run)
        return 1 if api.errors else 0

    by_dept = {}
    for it in items:
        by_dept.setdefault(it["dept"], []).append(it)

    # ★★未確認の不具合台帳へ積む(2026-07-29)。**投函より先に**やる。
    #   理由= 投函が全滅しても「壊れた実物の在りか」は世代をまたぐ器に残す(沈黙を作らない)。
    #   ★冪等なので、投函が失敗して次回まるごと拾い直しても台帳は増えない。
    d_add, d_dup, d_why = stack_open_defects(items, guild_id, a.dry_run)
    print(f"\n--- 未確認の不具合台帳(世代をまたぐ器) ---")
    if d_why:
        print(f"   ★積めなかった: {d_why}")
    else:
        print(f"   炎上+再発スタンプ {sum(1 for it in items if it.get('kind') in DEFECT_KINDS)}件 → "
              f"新しく積んだ {d_add}件 / 既にあった {d_dup}件")

    print("\n--- 投函内容 ---")
    posted, failed = [], []
    for dept in sorted(by_dept):
        if dept in SKIP_DEPTS:
            print(f"\n[{dept}] ★Chamiの部屋なので出さない({len(by_dept[dept])}件・一覧には載せる)")
            continue
        body = dept_body(dept, by_dept[dept], guild_id, realtime=bool(rt))
        print(f"\n[{dept}] {len(by_dept[dept])}件 / 本文{len(body)}字")
        if a.dry_run:
            print("---8<--- ここから本文 ---8<---")
            print(body)
            print("---8<--- ここまで本文 ---8<---")
        if send(dept, body, a.dry_run, sender=sender, tag=("rt_" if rt else "")):
            posted.extend(by_dept[dept])
        else:
            failed.append(dept)

    if rt:
        # ★実時間モードは「一報の運び屋」であって、その日の記録係ではない。
        #   一覧は書かない=朝の巡回が同じ改悪をもう一度拾い、そちらが一覧と集計に載る。
        print(f"\n[{KAIZEN_DEPT}] ★実時間モードでは一覧を書かない"
              "(朝8時の巡回が正本。ここで書くと脈と数え方が二重になる)")
        if a.dry_run:
            print("\n[dry-run] 台帳へは書かない。")
            return 0
        uniq = ledger_rows(items, posted)
        append_ledger(uniq, ledger_path)
        print(f"\n実時間の台帳へ {len(uniq)}/{len(items)}件を記録した({ledger_path}・冪等)。"
              f"投函できなかった部門: {','.join(failed) if failed else 'なし'}")
        return 1 if (failed or api.errors) else 0

    kbody = kaizen_body(items, guild_id, stats, a.hours)
    print(f"\n[{KAIZEN_DEPT}] 全部屋一覧 {len(items)}件 / 本文{len(kbody)}字 "
          "→ 配達せずファイルへ落とす(手2・改善提案部門が朝の便で読む)")
    # ★手2(2026-08-23): 一覧は dispatch で**起こさず**、ファイルへ書く。
    #   ★書き込みの成否が「行き先へ届いた」の判定(kok)= ここが台帳ゲート(下)を守る。
    #     書けなければ台帳へ何も書かない=次回まるごと拾い直す(従来と同じ不変条件)。
    #   ★dry-run は本番と同じく実ファイルは触らない(台帳も汚さない)= 中身を見せるだけ。
    #   ★書き口は write_kaizen_digest 1本(0件の枝と同じ関数)= 書式を2箇所に持たない。
    kok = write_kaizen_digest(kbody, len(items), a.dry_run)
    if not kok:
        failed.append(KAIZEN_DEPT)

    if a.dry_run:
        print("\n[dry-run] 台帳へは書かない。次に本番で流せば同じものが投函される。")
        return 0

    # ★台帳へ入れるのは「行き先すべてへ届いたもの」だけ。届かなかったものは次回もう一度拾う。
    #   行き先= ①その部屋(hqは出さないので最初から済み扱い) ②改善提案部門の一覧(手2以降=ファイル)。
    #   ★一覧のファイル書き込みが落ちた時は**何も記録しない**= 次回その部屋へ二重に出る可能性が残る。
    #     それでも「拾い漏らす」より「二度出る」方を採る(合図を落とす方が害が大きい)。
    #     ローカルへの書き込みなので、ここが落ちるのは相当な異常時に限られる(旧: dispatchのキュー投函)。
    if not kok:
        print("\n★改善提案部門への一覧をファイルへ書けなかったので、台帳へは何も書かない"
              "(次回まるごと拾い直す)。")
        return 1
    uniq = ledger_rows(items, posted)
    append_ledger(uniq, ledger_path)
    print(f"\n台帳へ {len(uniq)}/{len(items)}件を記録した(冪等)。投函できなかった部門: "
          f"{','.join(failed) if failed else 'なし'}")
    return 1 if (failed or api.errors) else 0


if __name__ == "__main__":
    sys.exit(main())
