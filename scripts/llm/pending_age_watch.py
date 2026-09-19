# -*- coding: utf-8 -*-
"""pending_age_watch — 「入れた(確認待ち)」に**日齢**を打ち、誰にも督促されないまま沈む穴を塞ぐ。

★なぜ在るか(2026-09-05 裁定 C-070・研究室HQ → イージス研究室 `DISPATCH-aegis-gl-1788503402548`)
  HQ実測= `00_AI-HQ/status/hq_open_items.md` の「確認待ち」84行。日付が読めた72件で最古46日・
  中央値22日。**入れた本人も、待っている側も、誰も日齢を見ていなかった。**
  → 3日超で**所有部門へ督促** / 7日超で**依頼元の部屋へ状態を1行**。
  ★**増分ではなく経過時間で鳴らす**(増分だけの監視は滞留を見逃す)。

★載せ方= 新しい定刻タスクを作らない。`watch_triggers.py` の **T6** として、既に定刻で回っている
  `quota_alarm.py` の頭から呼ばれる線に相乗りする(発火しない安全網は検証されない=§3)。

★在庫を一斉に鳴らさない(HQ要件4)= 状態ファイルに **基準日** を1回だけ焼き、
  **基準日より前の行は数えるが鳴らさない**。在庫の棚卸しはHQが別で持つ(HQ-0236)。

★日付が読めない行は「日齢不明」として**数だけ**出す(HQ要件5)。推定で埋めない(§4.55)。
  ただし拾い方はHQ指定の `★YYYY-MM-DD` だけでは足りない=**実測で 146行中100行が★を持たない**。
  行の中に素の `YYYY-MM-DD` が在ればそれも拾う(推測ではなく、行に書いてある字を読む)。
  どちらで読んだかは `date_src` に残す= 数え方を隠さない。

使い方:
  python scripts/llm/pending_age_watch.py --report     # 分布を見るだけ(便は出さない)
  python scripts/llm/pending_age_watch.py --dry-run    # 判定まで回して、出す便を画面に出す
  python scripts/llm/pending_age_watch.py              # 本番(T6 から呼ばれるのと同じ)
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HQ = os.path.join(os.path.dirname(ROOT), "00_AI-HQ")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
STATUS = os.path.join(HQ, "status")
REGISTRY = os.path.join(HQ, "org_registry.yml")
STATE = os.path.join(ROOT, "local", "llm", "pending_age_state.json")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")

# ★基準日= ここより前の行は「在庫」として数えるだけで鳴らさない(HQ要件4)。
#   2026-09-01(直近の週の頭)に切った理由= 実測で、今日(09-05)に切ると鳴る行は0件=
#   **発火しない安全網は検証されない**。09-01なら 6件/5便= 景色にならず、しかも全部が本物の遅延。
#   在庫(112件)の棚卸しはHQが HQ-0236 で別に持つ。
BASELINE_DEFAULT = "2026-09-01"
AGE_REMIND = 3.0        # 日。所有部門へ督促(C-070)
AGE_ESCALATE = 7.0      # 日。依頼元の部屋へ状態を1行(C-070)
MAX_LINES_PER_MAIL = 12  # 1便に並べる件数の上限(残りは件数だけ)
SEND_DRY = False         # 真= dispatch.py は本当に起動するが投函だけ止まる(watch_triggers と同じ作法)

# ★「入れた(確認待ち)」。★直前が「 の時は**その語について喋っている行**= 対象外
#   (例= HQ-0236「『入れた(確認待ち)』の在庫84行を片付ける」は棚卸しの起票であって確認待ちではない)
#   ★括弧の中に続きを書いた形も拾う= `入れた(確認待ち・所有=hq)`(C-072・2026-09-05 HQ裁定)。
#     旧`入れた\(確認待ち\)`だと閉じ括弧が来ないので **scan の入口(187行)で行ごと落ちて**
#     いた。誤配が直るどころか案件が消える= 実測で確かめた(local/_work/c072_probe.py)。
PENDING = re.compile(r"(?<!「)入れた\(確認待ち[^)）\n]*[)）]")
# ★打ち消し線= 書いた本人が**札を取り消した**印。`~~入れた(確認待ち)~~ → 直った` の形で閉じる。
#   2026-09-05 実測= この見張り自身が hq_open_items.md:731(呼称ゲートC・04:2xに閉じた行)を
#   4.3日の未確認として鳴らしていた。**閉じた仕事を催促するのは沈黙の逆の壊れ方**だ。
#   ★閉じ扱いにするのは打ち消し線だけ。「札の後ろに直った/効いたが在る」は使わない=
#     実測21行が該当し、その多くは本文で経緯を喋っているだけで閉じていない(取りこぼす)。
STRUCK = re.compile(r"~~.+?~~", re.S)
# ★★ブロックで開閉する台帳を、行で読んでいた(2026-09-18・AD研究室の実測返しで判明)。
#   書き手 `scripts/_daemons/teian_echo_poll.py` の `note_open_item()` は**追記のみ**で、
#   見出し行には二度と触らない(C-003= HQが並行して書くファイルを壊さない)。復旧時は
#     `<!-- teian-echo:read-fail RESOLVED 2026-09-15 01:12 -->` と `✅` を**下に足すだけ**。
#   = 見出し行の打ち消しは構造上いつまでも起きない → こちらからは**永久に開いて見える**。
#   実物= `hq_open_items.md:984-989`。01:02→01:12 の**10分**で閉じていた仕事を 3.2日の滞留として
#   鳴らし、しかも持ち主(次行に `platform-se` と書いてある)を見出しの機能名から「軍議」と当てた
#   =**閉じた仕事を、持っていない部門へ督促する**便(ORG-04の形)。§3「常に誤発火する安全網は
#   無視される」に当たるので、読み手のこちらを直す(書き手の追記のみは正しい設計だ)。
# ★閉じ判定は1つだけ= **同じ札の RESOLVED 印が、その見出しより下に在るか。**
#   書き手が `last == "OPEN"` の間は二度と開かない=OPENとRESOLVEDは必ず交互に並ぶので、
#   下に RESOLVED が在る見出しは、その時点で閉じている(次のOPENは別の見出しを連れてくる)。
# ★印が無い行は**何も変えない**= 判定不能なら鳴らす側へ倒す(fail-open・§3)。
# ★札を見るのは**ブロックの見出し行だけ**= 書き手の形は
#     `## <stamp> 提案決定→軍議エコー(経路B) = 入れた(確認待ち) [teian-echo:<kind>]`
#   で、`#`見出し + **行末の札**に固定されている(teian_echo_poll.py:400)。
#   ここを「行のどこかに札の形が在れば」で見ると、**札を本文で引用しただけの普通の行**まで
#   閉じ扱いで飲み込む。2026-09-18 に実際に起きた= この穴を直した時の台帳追記そのものが
#   `[teian-echo:read-fail]` を引用しており、hq_open_items.md:35(日齢0日・自分の案件)が
#   scan() から消えた。**沈黙は最悪の事故**(§3)なので、飲み込む側の条件はきつく縛る。
BLOCK_TAG = re.compile(r"\[([A-Za-z][\w\-]*:[\w\-]+)\]")
BLOCK_HEAD = re.compile(r"^\s*#{1,6}\s.*\[([A-Za-z][\w\-]*:[\w\-]+)\]\s*$")
RESOLVED_MARK = re.compile(r"<!--\s*([A-Za-z][\w\-]*:[\w\-]+)\s+RESOLVED\b")
# ★所有部門の明示。札の直後の部門名を当てに行く前に、**書いてあるならそれを採る**(C-072)。
OWNER_MARK = re.compile(r"所有\s*[=＝]\s*([A-Za-z0-9_\-]+|[^\s)）、。,]+)")
STAR_DATE = re.compile(r"★\s*(\d{4})-(\d{2})-(\d{2})")
ANY_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
ITEM_ID = re.compile(r"\b((?:HQ|ORG|INC)-\d{2,5}(?:-[A-Z])?)\b")
# ★子番号(`HQ-0213-C`)は**親とは別の案件**。ここを `HQ-0213` までしか読まないと、
#   下の closed_keys が「-A が閉じた」証拠で -C まで黙らせる。2026-09-20 に実測=
#   サフィックス付きは10種(HQ-0018-A / HQ-0206-A,B / HQ-0210-A,B / HQ-0213-A,B,C /
#   HQ-0214-A,B)で**全て半角大文字1文字**。素朴な key 一致案はこれで3件を誤って沈黙させた。
# ★台帳のID欄は行末の `\`HQ-0249\` @2026-09` という決まった形で書かれている(ID列)。
#   本文の中で**別の裁定番号を引き合いに出す**(例「ORG-11= 表を2か所に持つと必ず片方が腐る」)と、
#   素の ITEM_ID.search は行の**最初**の当たりを返すので、そちらを行のIDだと読み違える。
#   2026-09-08 に実際に起きた= HQ-0249 の行へ ORG-11 を引いた追記を入れた途端、督促の本文が
#   `ORG-11 hq_open_items.md:24` と名乗った(存在しない台帳IDを人へ渡す=ORG-04の形)。
#   → **ID列の形を先に見て、無い時だけ素の当たりへ落ちる。**
#   実測(2026-09-08・現行+アーカイブの「入れた(確認待ち)」168行)= ID列を持つ行は45行で
#   **1行に2つ現れる行は0件**、素の先頭と食い違うのは**上のHQ-0249の1行だけ**=巻き添え0。
ITEM_ID_COL = re.compile(r"`((?:HQ|ORG|INC)-\d{2,5}(?:-[A-Z])?)`\s*@\d{4}-\d{2}")
# ★アーカイブ側の「解決」を機械が読める唯一の形(2026-09-20 / シャビ・アロンソの指摘)。
#   閉じ判定の口はこれまで3つ= ①行頭の `- [x]` ②ブロックの `[ns:key] RESOLVED` 札
#   ③打ち消し線。②が見る札と台帳ID `HQ-xxxx` は**別体系**で、09アーカイブに RESOLVED 印は
#   0件。人が閉じる時に実際に書いているのは**見出しの `★解決`** だった。
#   → アーカイブへ `<!-- HQ-xxxx RESOLVED -->` を後付けして回るのではなく、
#     **機械が既存の書式を読めるようにする**(C-038= 書き手を増やさず読み手を直す)。
#   ★見出しに縛る理由は BLOCK_HEAD と同じ= 本文で「HQ-0271 は★解決済み」と触れただけの行
#     (09アーカイブ:662)まで証拠に数えると、生きている案件が黙って消える(§3)。
SOLVED_HEAD = re.compile(r"^\s*#{1,6}\s.*★\s*解決")


def item_id(text):
    """その行の台帳ID。ID列(`HQ-0249` @2026-09)が在ればそれ、無ければ素の最初の当たり。"""
    m = ITEM_ID_COL.search(text) or ITEM_ID.search(text)
    return m.group(1) if m else ""
# ★便のID(`DISPATCH-aegis-gl-1788556091239`)の中のスラッグは**宛先であって依頼元ではない**。
#   ここを読むと「発注= DISPATCH-aegis-gl-…」を自室発注と読み違える(2026-09-05 実測2行)。
#   → 専用の伏せ字は置かない。`_find_name` の語境界(前後がASCII語字なら拾わない)が同じ穴を
#     塞ぐことを実測で確かめた= 伏せ字を足しても判定は1行も変わらない。**機構を2本持たない。**
CHECKBOX = re.compile(r"^\s*-\s*\[([ xX])\]")
# 依頼元の合図。この後ろに出てくる最初の部門名を「待っている側」と読む
REQ_MARK = re.compile(r"(?:発注|裁定|依頼|起票|指示|依頼元)\s*=")

# ★2026-09-05 ここに在った EXTRA_ALIASES(通称のハードコード表)は**退役**した。HQ-0241。
#   理由= 同じ通称が台帳(org_registry.yml の aliases)とコードの2箇所に在ると、片方だけ
#   直した時に**呼び出し元によって答が割れる**。実際、HQが台帳へ通称を5部門ぶん足した
#   直後に試験が 16/16 → 15/16 へ落ちた(コード側が古い表を持っていたため)。
#   移設先= `hq:[HQ]` / `aegis-gl:[イージスGL]` / `ai-office:[改修γ]`(00_AI-HQ org_registry.yml)。
#   `ad研究室` は alias を足さず **dept_names 側の正規化(大小・全半角)で吸う**。
#   表は `dept_names.dept_scan_map()` 1本(ORG-11= 判定を2本持たない)。


def read_json(path, default=None):
    try:
        with io.open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def dept_aliases():
    """部門名 → スラッグ。**表は持たない**= `dept_names.dept_scan_map()` を引くだけ(ORG-11)。

    正本= org_registry.yml の display_ja(正式名)と aliases(通称)。C-073 でこの見張りへ
    通称を配線したが、その時コード側の EXTRA_ALIASES を残したのが二重管理だった(HQ-0241)。
    ★台帳が読めない時は**空の表**が返る= 持ち主が当たらないだけで、便は消えない
      (`decide().to()` が台帳の持ち主=研究室HQへ倒す)。沈黙にはしない。
    """
    sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
    from dept_names import dept_scan_map
    m = dept_scan_map()
    if not m:
        print("  ★部門名の表が空だ(org_registry.yml を読めていない)。持ち主はHQへ倒す")
    return m


def rooms(registry=REGISTRY):
    """部屋が実在する部門のスラッグ。★居ない相手に預けない= 偽の受領が沈黙を隠す。"""
    try:
        import yaml
        doc = yaml.safe_load(io.open(registry, encoding="utf-8")) or {}
        return {c.get("dept") for c in (doc.get("channels") or []) if c.get("dept")}
    except Exception:
        return set()


ASCII_WORD = re.compile(r"[0-9A-Za-z_\-]")


def _find_name(text, name):
    """`name` が**語として**出る一番左の位置。無ければ -1。

    ★2026-09-05= 純ASCIIの短い名前(`HQ` / `hq` / `hr-room`)は、パスやコマンドの中に
      埋もれている字面を持ち主と読んでしまう。実測= `00_AI-HQ/personas/口調ルール.json`
      の "HQ" を行の一番左として拾い、持ち主=研究室HQ と判定していた(HQ-0241の調べ)。
      → 純ASCIIの名前だけ、前後がASCII語字でないことを要求する(語の途中では拾わない)。
      日本語名(イージス研究室 等)は語境界が無いので従来どおり素直に探す。
    """
    if not name.isascii():
        return text.find(name)
    n, start = len(name), 0
    while True:
        i = text.find(name, start)
        if i < 0:
            return -1
        pre = text[i - 1] if i else ""
        post = text[i + n] if i + n < len(text) else ""
        if not (ASCII_WORD.match(pre) or ASCII_WORD.match(post)):
            return i
        start = i + 1


def _leftmost(text, alias):
    """行の中で**一番左**に出る部門名を返す。見出しや札は行頭側に在る=そこが持ち主。"""
    best = None
    for name, slug in alias.items():
        i = _find_name(text, name)
        if i < 0:
            continue
        # 同じ位置から始まるなら長い方(「改修部門α」>「改修α」)
        if best is None or i < best[0] or (i == best[0] and len(name) > best[2]):
            best = (i, slug, len(name))
    return best


def parse_line(text, alias):
    """1行から (日付, date_src, 所有部門, 依頼元) を読む。読めない所は None。"""
    m = STAR_DATE.search(text)
    src = "star"
    if not m:
        m = ANY_DATE.search(text)
        src = "line"
    date = None
    if m:
        try:
            date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=JST)
        except ValueError:
            date = None
    if date is None:
        src = None

    # ★台帳IDを伏せてから部門名を探す= `HQ-0034` の "HQ" を持ち主と読み違えない
    masked = ITEM_ID.sub("  ", text)
    # 持ち主は「入れた(確認待ち)・<部門>」の形で札の直後に書かれることが多い= そこを先に見る。
    # 無ければ行の一番左(見出し・commit札が行頭側に在る)。★どちらも当て推量ではなく字面。
    owner = None
    # ★書いてあるなら当て推量しない= `所有=hq` / `所有=研究室HQ`(C-072)。
    #   起点(誰が言い出したか)と所有(誰が入れたか)が裸で並ぶ行を機械が読み違えた実物
    #   (DISPATCH-research-room-1788547775012)への直し。
    om = OWNER_MARK.search(masked)
    if om:
        tok = om.group(1).strip()
        if tok in alias:
            owner = alias[tok]
        else:
            near = _leftmost(tok, alias)
            owner = near[1] if near else None

    pm = PENDING.search(masked)
    if not owner and pm:
        near = _leftmost(masked[pm.end():pm.end() + 30], alias)
        owner = near[1] if near else None
    if not owner:
        near = _leftmost(masked, alias)
        owner = near[1] if near else None

    req = None
    rm = REQ_MARK.search(masked)
    if rm:
        tail = _leftmost(masked[rm.end():rm.end() + 60], alias)
        if tail:
            req = tail[1]
    return date, src, owner, req


def ledger_files(status=STATUS):
    """対象= 現行 + 月別アーカイブ(HQ要件1)。.bak は見ない(退避であって台帳ではない)。"""
    out = [os.path.join(status, "hq_open_items.md")]
    out += sorted(glob.glob(os.path.join(
        status, "archive", "hq_open_items_[0-9][0-9][0-9][0-9]-[0-9][0-9].md")))
    return [p for p in out if os.path.exists(p)]


def resolved_marks(lines):
    """札 → その札の `RESOLVED` 印が出る**最後の行番号**(1始まり)。印が無い札は入らない。"""
    out = {}
    for no, raw in enumerate(lines, 1):
        m = RESOLVED_MARK.search(raw)
        if m:
            out[m.group(1)] = no
    return out


def block_closed(text, no, marks):
    """その行が**ブロックの見出し**で、かつ下に同じ札の RESOLVED 印が在るか。

    ★見出しの形(`#`+行末の札)でない行は**絶対に飲み込まない**= 本文で札を引用しただけの
      普通の案件行を消さないため(2026-09-18 の実物= hq_open_items.md:35)。
    """
    m = BLOCK_HEAD.match(text)
    if not m:
        return False
    return marks.get(m.group(1), 0) > no


def file_rank(files):
    """ファイルの**新しさ**の順位。ledger_files() の並びは [現行, 2026-07, 2026-08, …]=
    先頭の現行が一番新しく、残りは年月の昇順。順位を採るのは下の closed_keys のためだけ。"""
    return dict((p, (10 ** 6 if i == 0 else i)) for i, p in enumerate(files))


def closed_keys(files, rank):
    """台帳IDごとに「閉じた証拠」の位置 [(ファイル順位, 行番号, ファイル名), …]。

    ★証拠として数えるのは2つだけ=
      ① 行頭が `- [x]` で、その行の item_id が読める(人が台帳で閉じた形)
      ② `SOLVED_HEAD` に当たる**見出し**(アーカイブで人が閉じた形)
    ★位置を持たせる理由= **同じIDが別案件へ再利用されている**(実測: HQ-0221 が09アーカイブの
      516行で閉じ、550行で別件として開き直している)。位置を捨てて「IDが一度でも閉じたか」で
      見ると、後から開いた方まで黙る。→ 使うのは**保留行より後ろ**に在る証拠だけ(scan 側)。
    """
    out = {}
    for path in files:
        for no, raw in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
            cb = CHECKBOX.match(raw)
            if not ((cb and cb.group(1).lower() == "x") or SOLVED_HEAD.match(raw)):
                continue
            mid = item_id(raw)
            if mid:
                out.setdefault(mid, []).append((rank[path], no, os.path.basename(path)))
    return out


def scan(now, files=None, alias=None):
    """台帳を1周して「入れた(確認待ち)」行を全部拾う。**判定はしない**(数えるだけ)。

    ★2026-09-20 追加= ①他ファイルの閉じた証拠で落とす ②同じ台帳IDを1件に畳む。
      どちらも「1件を何度も鳴らす/閉じた件を鳴らす」= 見張りへの信用を削る形だった
      (04:00の便が「7日超過5件」と出して実体は3件)。
    """
    alias = alias if alias is not None else dept_aliases()
    items = []
    files = list(files if files is not None else ledger_files())
    rank = file_rank(files)
    closed = closed_keys(files, rank)
    for path in files:
        lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
        marks = resolved_marks(lines)          # ★ブロックの状態印は行より先に1周して集める
        for no, raw in enumerate(lines, 1):
            text = raw.rstrip("\n")
            live = STRUCK.sub("  ", text)      # 取り消した札は「もう無い字」として扱う
            if not PENDING.search(live):
                continue
            cb = CHECKBOX.match(text)
            if cb and cb.group(1).lower() == "x":
                continue                       # 閉じ済みのチェックボックスは対象外
            if block_closed(text, no, marks):
                continue                       # ★ブロックの状態印で閉じている(見出しは触られない)
            mid = item_id(text)
            if mid and [e for e in closed.get(mid, ())
                        if (e[0], e[1]) > (rank[path], no)]:
                continue                       # ★後ろの版で閉じている(現行の `- [x]` / `★解決`)
            date, src, owner, req = parse_line(live, alias)
            key = mid or "L" + hashlib.sha1(
                text.strip().encode("utf-8")).hexdigest()[:10]
            items.append({
                "key": key,
                "file": os.path.basename(path),
                "line": no,
                "date": date.strftime("%Y-%m-%d") if date else None,
                "date_src": src,
                "age": round((now - date).total_seconds() / 86400.0, 1) if date else None,
                "dept": owner,
                "req": req or "hq",          # 台帳の持ち主= 研究室HQ(読めない時の受け皿)
                "head": text.strip()[:110],
                "dup": 0,                    # 同じ台帳IDで畳んだ**他の**行の数
            })
    return fold(items)


def fold(items):
    """同じ台帳IDの行を1件に畳む(欠陥2= 1回の便に同じ札が二重で載る)。

    ★残すのは**現行ファイル側**= scan の周回順で先に来る方。アーカイブの古い写しではなく
      今の台帳の行を人へ渡すため(便に出る `file:line` がそのまま開ける場所になる)。
    ★例外は1つ= 残した側が日付を読めず、畳む側が読める時だけ差し替える。日齢が読めない行は
      督促の本数を決められない= 判定できる方を残す(§3 fail-open)。
    ★`key` が `L…`(IDの無い行のハッシュ)の時も同じ字面なら畳んでよい= 同じ行の写し。
    """
    out, at = [], {}
    for it in items:
        i = at.get(it["key"])
        if i is None:
            at[it["key"]] = len(out)
            out.append(it)
            continue
        out[i]["dup"] += 1
        if out[i]["age"] is None and it["age"] is not None:
            it["dup"] = out[i]["dup"]
            out[i] = it
    return out


def summarize(items, baseline):
    """数え方を添えた分布。★不明は不明のまま数える(§4.55)。"""
    dated = [i for i in items if i["age"] is not None]
    unknown = [i for i in items if i["age"] is None]
    fresh = [i for i in dated if i["date"] >= baseline]
    stock = [i for i in dated if i["date"] < baseline]
    ages = sorted(i["age"] for i in dated)
    return {
        "total": len(items),
        "dated": len(dated),
        "unknown": len(unknown),
        "by_star": len([i for i in dated if i["date_src"] == "star"]),
        "by_line": len([i for i in dated if i["date_src"] == "line"]),
        "fresh": len(fresh),
        "stock": len(stock),
        "oldest": ages[-1] if ages else None,
        "median": ages[len(ages) // 2] if ages else None,
        "over3": len([i for i in dated if i["age"] > AGE_REMIND]),
        "over7": len([i for i in dated if i["age"] > AGE_ESCALATE]),
        "no_dept": len([i for i in items if not i["dept"]]),
        "folded": sum(i.get("dup", 0) for i in items),   # 同じ台帳IDで畳んだ行の数
    }


def decide(items, baseline, fired, live=None):
    """鳴らす対象を決める。★基準日より前(=在庫)は**数えるが鳴らさない**(HQ要件4)。

    返り値= (3日超で督促する部門ごとの束, 7日超で報告する部屋ごとの束)
    """
    live = rooms() if live is None else live

    def to(slug):
        # 部屋が無い部門へ投げると便が消える= 台帳の持ち主(研究室HQ)が受け取る
        return slug if (slug and (not live or slug in live)) else "hq"

    d3, d7 = {}, {}
    for it in items:
        if it["age"] is None or it["date"] < baseline:
            continue
        st = fired.get(it["key"]) or {}
        if it["age"] > AGE_ESCALATE and not st.get("d7"):
            d7.setdefault(to(it["req"]), []).append(it)
        elif it["age"] > AGE_REMIND and not st.get("d3"):
            d3.setdefault(to(it["dept"]), []).append(it)
    for g in (d3, d7):
        for v in g.values():
            v.sort(key=lambda x: -x["age"])
    return d3, d7


def _rows(items):
    out = []
    for it in items[:MAX_LINES_PER_MAIL]:
        out.append("  - **%.1f日** `%s` %s:%s%s\n      %s"
                   % (it["age"], it["key"], it["file"], it["line"],
                      "" if it["date_src"] == "star" else "(★印なし=行内の日付で読んだ)",
                      it["head"]))
    if len(items) > MAX_LINES_PER_MAIL:
        out.append("  - …ほか %d件(全部は台帳側に在る)" % (len(items) - MAX_LINES_PER_MAIL))
    return "\n".join(out)


def _foot(stats, baseline):
    return ("\n★数え方= `status/hq_open_items.md` + `status/archive/hq_open_items_<年-月>.md` の"
            "「入れた(確認待ち)」行 %d件を1周。日付が読めたのは %d件"
            "(★印 %d / 行内の日付 %d)、**日齢不明 %d件**(推定で埋めていない)。\n"
            "%s"
            "★基準日 %s より前の %d件(在庫)は数えたが鳴らしていない= 棚卸しはHQが別で持つ(HQ-0236)。\n"
            "★宛先は台帳の字面から機械が当てている(札の直後の部門名 → 無ければ行の一番左)。"
            "違うなら1行返してくれ= 誤配は台帳の書き方の側で直す。\n"
            "★出所= 裁定 C-070 / 見張り `scripts/llm/pending_age_watch.py`(定刻 watch_triggers T6)。"
            % (stats["total"], stats["dated"], stats["by_star"], stats["by_line"],
               stats["unknown"],
               ("★アーカイブと現行に同じ台帳IDで載っていた %d行は1件へ畳んだ"
                "(残したのは現行の台帳側の行)。\n" % stats["folded"])
               if stats.get("folded") else "",
               baseline, stats["stock"]))


GUARD_LEAD = re.compile(r"の部門長は\s*'([A-Za-z0-9_-]+)'")


def _dispatch_once(dept, text):
    path = os.path.join(ROOT, "local", "_pending_age_body.txt")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    cmd = [sys.executable, DISPATCH, "--dept", dept, "--from-dept", "aegis-gl",
           "--from", "日齢の見張り(定刻・イージス研究室)", "--audience", "ai",
           "--body-file", path]
    if SEND_DRY:                    # ★配線の検証用= dispatch.py は本当に起動し、投函だけ止まる
        cmd.append("--dry-run")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    print("   dispatch %s rc=%s %s" % (dept, p.returncode, out[:160]))
    return p.returncode, out


def send_dispatch(dept, title, body, dry):
    """便を1本。★宛先は台帳から機械が決める= 人手の入口を要件にしない(§3)。"""
    text = "【日齢の見張り(C-070)】%s\n\n%s" % (title, body)
    if dry:
        print("---- dry-run(送らない) → dept=%s ----\n%s\n" % (dept, text))
        return True
    rc, out = _dispatch_once(dept, text)
    if rc == 0:
        return True
    # ★3階梯(RULES §6.4)で弾かれたら、その部門の部門長へ回す。
    #   ここで --direct へ逃げない= 飛び級を機構で誤魔化すと、階梯が形だけになる。
    m = GUARD_LEAD.search(out)
    if m and m.group(1) != dept:
        lead = m.group(1)
        note = ("★本来の宛先= **%s**。3階梯(RULES §6.4)でイージス研究室から直接は出せないので、"
                "部門長の当室へ回した。配下への割り振りを頼む。\n\n" % dept)
        rc2, _ = _dispatch_once(lead, "【日齢の見張り(C-070)】" + note + title + "\n\n" + body)
        return rc2 == 0
    return False


def run(now=None, dry=False, sender=None, state_path=STATE, files=None, save=True):
    """T6の本体。**鳴らした分だけ**状態へ焼く(同じ便を毎時間送り直さない)。"""
    now = now or datetime.now(JST)
    sender = sender or send_dispatch
    st = read_json(state_path, {}) or {}
    baseline = st.get("baseline") or BASELINE_DEFAULT
    fired = st.setdefault("fired", {})

    items = scan(now, files=files)
    stats = summarize(items, baseline)
    print("T6 確認待ち %d件(日付あり %d / 不明 %d)・3日超 %d / 7日超 %d ・基準日 %s(在庫 %d件は鳴らさない)"
          % (stats["total"], stats["dated"], stats["unknown"],
             stats["over3"], stats["over7"], baseline, stats["stock"]))
    d3, d7 = decide(items, baseline, fired)
    if not d3 and not d7:
        if save and not dry:
            st["baseline"] = baseline
            st["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%S")
            write_json(state_path, st)
        return 0

    n = 0
    for dept, rows in sorted(d3.items()):
        ok = sender(dept, "**%d件が3日を超えた**。入れた本人の確認が要る。" % len(rows),
                    "「入れた(確認待ち)」のまま日齢が3日を超えた行だ。**入れただけでは閉じない**"
                    "(§4.55)= 壊れていたのと同じ場面の実物を見て `close_item.py` か台帳で閉じるか、"
                    "**まだ見られていないなら『まだ見ていない』と1行書け**。\n\n"
                    + _rows(rows) + "\n" + _foot(stats, baseline), dry)
        if ok:
            n += 1
            for it in rows:
                fired.setdefault(it["key"], {})["d3"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    for dept, rows in sorted(d7.items()):
        ok = sender(dept, "**%d件が7日を超えた**。依頼元の部屋へ状態を出す。" % len(rows),
                    "3日の督促を過ぎても閉じていない行だ。**待っている側が知らないまま沈むのが"
                    "C-070の穴**= 進んでいないなら進んでいないと書けばいい。\n\n"
                    + _rows(rows) + "\n" + _foot(stats, baseline), dry)
        if ok:
            n += 1
            for it in rows:
                d = fired.setdefault(it["key"], {})
                d["d7"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                d.setdefault("d3", d["d7"])
    if save and not dry:
        st["baseline"] = baseline
        st["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%S")
        write_json(state_path, st)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="分布だけ見る(判定も送信もしない)")
    ap.add_argument("--dry-run", action="store_true", help="判定まで回して便は画面に出すだけ")
    a = ap.parse_args()
    now = datetime.now(JST)
    if a.report:
        items = scan(now)
        st = read_json(STATE, {}) or {}
        base = st.get("baseline") or now.strftime("%Y-%m-%d")
        s = summarize(items, base)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        for it in sorted([i for i in items if i["age"] is not None],
                         key=lambda x: -x["age"])[:15]:
            print("  %6.1f日 %-10s %-24s:%-5s %s" % (it["age"], it["dept"] or "-",
                                                     it["file"], it["line"], it["head"][:70]))
        return 0
    print("→ 発火 %d本" % run(now, dry=a.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
