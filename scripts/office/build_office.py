#!/usr/bin/env python3
"""AIオフィス: 実データから部屋型バーチャルオフィスHTMLを生成する。

設計: docs/設計・調査/AIオフィス_部屋型_設計書_v1.md
改善: docs/設計・調査/AIオフィス_部屋型_改善書_v1.md (K-0〜K-10をここで実装)
純粋関数: scripts/office/office_core.py (時刻・slug正規化・在席判定・立ち絵選択) / テスト=tests/test_office.py

原則(絶対に崩さない):
  **偽Status禁止** — 吹き出し・状態は全て実データ由来。実データが無い時に「それらしい状態」を作らない。
  ★取得に失敗した時は「待機中」ではなく **「取得失敗=不明」** と表示する(K-0/F1)。
    失敗を隠して全部門ヒマの顔をするのが、この画面で最も質の悪い嘘になる。
  ★脈が古い窓を「不在」と断定しない(K-6/INC-94)。waiterの脈は新着を配達した瞬間に止まるため、
    脈なし=不在 or 処理中で **判別できない**。断定できないものは断定しない。

台帳駆動(K-7): 部屋・所属・色・顔・idleは全て台帳を読む。このファイルに組織を手書きしない。
  部屋   = local/discord_channels.json (鳩の巡回対象=新部門は必ずここに載る)
  所属   = docs/departments/personas/INDEX.md (「所属の正はこの台帳とする」と明文化されている)
  色     = local/persona_colors.json / 顔 = local/persona_avatars.json / 立ち絵 = local/persona_sprites.json
  idle   = docs/departments/personas/*/persona_manifest.yml
  表示の調整(除外・ラベル・並び)のみ local/office_rooms.json

自己完結(K-9/NEW-3): アバターはビルド時に local/office/assets/ へ取り込み、HTMLからは相対参照する。
  = オフライン閲覧可・CDN/Worker失効に影響されない・閲覧のたびに外部へ通信が飛ばない。
  (単一ファイルへのbase64焼き込みは1枚400KB級のため採らない。HTML+assetsで外部依存ゼロを満たす)

出力: local/office/index.html (非公開=ローカル専用)
使い方: python scripts/office/build_office.py [--open]
終了コード: 0=全取得成功 / 1=一部または全部の取得に失敗(HTMLは警告付きで生成される)
"""
import argparse
import datetime
import glob
import hashlib
import html
import json
import os
import random
import re
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from office_core import (  # noqa: E402
    PRESENCE_LABEL, canon_name, bubble_state, esc, is_jst_today, jst_str, latest_ts,
    normalize_dept, normalize_sprites, parse_idle_text, pick_sprite, presence_state, to_jst,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
OUT_DIR = os.path.join(LOCAL, "office")
OUT = os.path.join(OUT_DIR, "index.html")
ASSETS = os.path.join(OUT_DIR, "assets")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) go5-office-build"


# ── 小さなI/Oヘルパ ───────────────────────────────────────────────
def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default if default is not None else {}


def read_text(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def mtime_of(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def epoch_jst(ep):
    """epoch秒 → JST表示。Noneは空(utcfromtimestampは3.12で非推奨のため使わない)。"""
    if not ep:
        return ""
    return jst_str(datetime.datetime.fromtimestamp(ep, datetime.timezone.utc).replace(tzinfo=None))


# ── 台帳(SSOT)の読み込み ─────────────────────────────────────────
def load_rooms_config():
    """表示調整のみ(除外・ラベル・並び)。組織そのものはここに書かない。"""
    return read_json(os.path.join(LOCAL, "office_rooms.json"), {})


def load_channels():
    ch = read_json(os.path.join(LOCAL, "discord_channels.json"), [])
    return [c for c in ch if isinstance(c, dict) and c.get("dept")]


def load_membership():
    """INDEX.md(所属の正)から {dept: [表示名,…]} を組み立てる。

    ①本表の「キャラ名 | 部門/部屋」行 ②散文セクションの「メンバー」宣言(改修3部屋・data-org等)
    の両方を拾う。名簿に載っていない部屋は **空のまま** 返す(=ドリフト報告で可視化する)。
    """
    path = os.path.join(ROOT, "docs", "departments", "personas", "INDEX.md")
    text = read_text(path)
    known = sorted({c["dept"] for c in load_channels()}, key=len, reverse=True)
    extra_slugs = ["incident-recovery"]           # INDEX表記→normalize_deptでslugへ寄る語
    members = {}

    def add(dept, name):
        d = normalize_dept(dept)
        n = canon_name(str(name).split("。")[0])       # 「アスナ(専任)。復旧部門に兼任追加」の後段を落とす
        if not n or n.startswith("(") or len(n) > 12:  # 長すぎる=人名でない(部屋名・説明文の混入除け)
            return
        members.setdefault(d, [])
        if n not in members[d]:
            members[d].append(n)

    # ① 本表(冒頭のペルソナ台帳に限定)。以降の ### 節には部屋一覧表・呼称マトリクスがあり、
    #    行頭|を無差別に拾うと「部屋名」まで部員として混入する。
    for line in text.split("\n### ")[0].splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].startswith("---") or cells[0] in ("キャラ名", "話者", "部屋"):
            continue
        name, dept_cell = cells[0], cells[1]
        if "研究室" in dept_cell:                  # 「研究室(main)が演じる」
            add("research-room", name)
        for slug in known + extra_slugs:
            if re.search(re.escape(slug) + r"(?![\w-])", dept_cell):
                add(slug, name)

    # ② 散文セクション(### 見出し単位)。「メンバー(は|=|:)」行の名前列を、その節が名指すdeptへ。
    #   例: 改修3部屋体制(α/β/γ共通メンバー) / data-org / incident-recovery は本表でなくここで宣言される。
    for sec in re.split(r"\n#{2,3} ", text):
        sec = sec.replace("**", "")                    # markdown強調を先に落とす(『**メンバー**:』を拾うため)
        slugs = [s for s in (known + extra_slugs)
                 if re.search(r"`" + re.escape(s) + r"`|dept[=:]\s*`?" + re.escape(s) + r"|[(（]" + re.escape(s) + r"[)）]", sec)]
        if not slugs:
            continue
        for m in re.finditer(r"メンバー(?:\(兼任\))?(?:は[^=:：\n]*)?[=:：]\s*([^\n]+)", sec):
            for raw in re.split(r"[/／]", m.group(1)):
                raw = raw.strip(" 　。")
                if not raw or raw.startswith("("):
                    continue
                for s in slugs:
                    add(s, raw)
    return members


def load_idle_texts():
    """persona_manifest.yml(idleの正本)から {キャラ正規名: [演出文,…]}。

    manifestは 'name:' と 'idle:' の平坦な列なのでyaml無しで拾う(依存を増やさない)。
    """
    out = {}
    for p in glob.glob(os.path.join(ROOT, "docs", "departments", "personas", "*", "persona_manifest.yml")):
        cur = None
        for line in read_text(p).splitlines():
            m = re.match(r"\s*-?\s*name:\s*(.+)", line)
            if m:
                cur = canon_name(m.group(1).strip())
                continue
            m = re.match(r"\s*idle:\s*(.+)", line)
            if m and cur:
                texts = parse_idle_text(m.group(1))
                if texts:
                    out.setdefault(cur, [])
                    out[cur] += [t for t in texts if t not in out[cur]]
    return out


def load_avatars():
    raw = read_json(os.path.join(LOCAL, "persona_avatars.json"), {})
    out = {}
    for k, v in raw.items():
        url = v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else None)
        if url:
            out[canon_name(k)] = url
    return out


def load_colors():
    return {canon_name(k): v for k, v in read_json(os.path.join(LOCAL, "persona_colors.json"), {}).items()}


# ── D1(失敗を隠さない) ───────────────────────────────────────────
class D1Error(Exception):
    pass


def _npx():
    return shutil.which("npx") or shutil.which("npx.cmd") or "npx"


def _extract_json(text):
    """wranglerの出力に混じる警告行を飛ばしてJSON本体を取り出す。

    先頭の '[' を単純検索すると '[WARNING]' に誤爆してデータ全損→[]化する(F1)。
    ここでは候補位置ごとにraw_decodeを試し、**本当にJSONとして読めた物だけ**を採る。
    """
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            val, _ = dec.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(val, list):
            return val
    raise D1Error("JSONが見つからない: " + (text or "")[:200].replace("\n", " "))


def fetch_d1(queries):
    """1回のwrangler呼び出しで複数SQLを取得(起動コストが遅さの正体=F5)。

    戻り値: (ok, {key: rows}, error)。失敗しても例外を投げず ok=False を返し、
    呼び出し側が「不明」として **正直に表示** できるようにする。
    """
    keys = list(queries.keys())
    sql = "; ".join(queries[k].rstrip(";") for k in keys)
    cmd = [_npx(), "wrangler", "d1", "execute", "go5_kaizen", "--remote", "--json", "--command", sql]
    cwd = os.path.join(ROOT, "fanza-worker")
    if not os.path.isdir(cwd):
        return False, {}, f"fanza-worker が無い: {cwd}"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=cwd, timeout=180)
    except subprocess.TimeoutExpired:
        return False, {}, "wranglerがタイムアウト(180秒)"
    except OSError as e:
        return False, {}, f"wranglerを起動できない: {e}"
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().replace("\n", " ")
        return False, {}, f"wrangler失敗(code={r.returncode}): {msg[:200]}"
    try:
        data = _extract_json(r.stdout or "")
    except D1Error as e:
        return False, {}, str(e)
    if len(data) < len(keys):
        return False, {}, f"結果セット不足(期待{len(keys)}・実際{len(data)})"
    return True, {k: (data[i].get("results") or []) for i, k in enumerate(keys)}, ""


D1_QUERIES = {
    "tasks": "SELECT assigned_dept,status,summary,result,created_at,completed_at FROM dept_tasks ORDER BY id DESC LIMIT 500",
    "events": "SELECT created_at,event_type,source_dept,summary FROM dept_events ORDER BY id DESC LIMIT 25",
    "changes": "SELECT created_at,component,summary FROM system_changes ORDER BY id DESC LIMIT 200",
    "reqs": "SELECT req_code,department,problem,status FROM improvement_requests ORDER BY id DESC LIMIT 50",
    "learning": "SELECT created_at,topic,question_text,answered_at FROM learning_questions ORDER BY id DESC LIMIT 5",
    "copy": "SELECT created_at,field,final_text FROM copy_revisions ORDER BY id DESC LIMIT 3",
    "research": "SELECT created_at,project,topic,status FROM research_notes ORDER BY id DESC LIMIT 3",
}


# ── ローカル実データ(D1不要・ネットワーク0) ──────────────────────
def load_presence(now):
    """{dept: (state, label, session_label, last_seen)}。脈=inbox_waiterが打つmtime。"""
    out = {}
    for p in glob.glob(os.path.join(LOCAL, "llm", "claude_active*.txt")):
        base = os.path.basename(p)
        dept = "research-room" if base == "claude_active.txt" else base[len("claude_active_"):-len(".txt")]
        dept = normalize_dept(dept)
        mt = mtime_of(p)
        prev = out.get(dept)
        if prev and prev[3] and mt and prev[3] >= mt:
            continue
        st = presence_state(mt, now)
        label = ""
        for cand in ([f"session_label_{dept}.txt"] + (["session_label.txt"] if dept == "research-room" else [])):
            label = read_text(os.path.join(LOCAL, "llm", cand)).strip()
            if label:
                break
        out[dept] = (st, PRESENCE_LABEL[st], label, mt)
    return out


def count_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def load_inbox_counts():
    """{dept: 配達済み未処理件数}。詰まり(誰も取っていない)の可視化。"""
    out = {}
    for p in glob.glob(os.path.join(LOCAL, "inbox", "*.jsonl")):
        dept = normalize_dept(os.path.splitext(os.path.basename(p))[0])
        n = count_lines(p)
        if n:
            out[dept] = n
    n = count_lines(os.path.join(LOCAL, "discord_inbox.jsonl"))
    if n:
        out["_main"] = n
    return out


def load_daemons():
    """常駐(郵便室)の死活。supervisorログの最終パスを読む。ここが死ぬと組織全体が沈黙する。"""
    log = os.path.join(LOCAL, "_daemons_supervisor.log")
    text = read_text(log)
    if not text:
        return [], None
    lines = text.splitlines()
    seen, order = {}, []
    for line in reversed(lines[-80:]):
        m = re.search(r"(\w[\w_.-]*):\s*(ok|start|restart|dead|stopped|fail\w*)\b(.*)$", line, re.I)
        if not m:
            continue
        name, st = m.group(1), m.group(2).lower()
        if name in ("go5", "supervisor") or name in seen:
            continue
        seen[name] = st
        order.append(name)
        if len(order) >= 6:
            break
    return [(n, seen[n]) for n in reversed(order)], mtime_of(log)


def load_git_log(n=5):
    try:
        r = subprocess.run(["git", "log", f"-{n}", "--format=%h\x1f%cI\x1f%s"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=ROOT, timeout=20)
        if r.returncode != 0:
            return []
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            out.append({"hash": parts[0], "ts": parts[1], "subject": parts[2]})
    return out


def load_latest_incident():
    """インシデント台帳の最新INC(設計書§2がヘッダに約束していた実データ源)。"""
    text = read_text(os.path.join(ROOT, "インシデント.md"))
    best = None
    for m in re.finditer(r"^##\s*INC-(\d+)\s*\(([\d-]+)\)\s*(.*)$", text, re.M):
        num = int(m.group(1))
        if best is None or num > best[0]:
            best = (num, m.group(2), m.group(3))
    return best


# ── アバターの取り込み(自己完結) ─────────────────────────────────
def localize_asset(url, report):
    """URLを local/office/assets/ へ取り込み、相対パスを返す。失敗はNone(=色ブロックへ劣化)。"""
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        return None
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = ".img"
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext
    dest = os.path.join(ASSETS, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "assets/" + name                      # キャッシュ済=通信しない
    os.makedirs(ASSETS, exist_ok=True)
    data = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except Exception:
        curl = shutil.which("curl")
        if curl:
            try:
                r = subprocess.run([curl, "-fsSL", "-A", UA, url], capture_output=True, timeout=30)
                data = r.stdout if r.returncode == 0 and r.stdout else None
            except (OSError, subprocess.TimeoutExpired):
                data = None
    if not data:
        report.append(f"アバター取得失敗: {url[:60]}")
        return None
    with open(dest, "wb") as f:
        f.write(data)
    return "assets/" + name


# ── 部屋の組み立て ────────────────────────────────────────────────
def short_label(ch_name, dept):
    """チャンネル名から見出しを作る(長い実名をそのまま出さない)。"""
    s = re.sub(r"[🌙🌱🚨👤⚙️]", "", ch_name or dept).strip()
    s = re.split(r"[-—]", s)[0].strip()
    return s or dept


def build_rooms(ctx):
    cfg, ok = ctx["cfg"], ctx["d1_ok"]
    rooms, drift = [], []
    tasks_by = {}
    for t in ctx["tasks"]:
        tasks_by.setdefault(normalize_dept(t.get("assigned_dept")), []).append(t)

    exclude = set(cfg.get("exclude") or [])
    labels = cfg.get("labels") or {}
    order = cfg.get("order") or []
    chans = [c for c in ctx["channels"] if c["dept"] not in exclude]
    chans.sort(key=lambda c: (order.index(c["dept"]) if c["dept"] in order else len(order)))

    known_depts = {c["dept"] for c in ctx["channels"]}
    for d in sorted(tasks_by):
        if d not in known_depts:
            drift.append(f"D1に部屋の無いdept: {d} ({len(tasks_by[d])}件) → 『未分類』へ表示中")

    for c in chans:
        dept = c["dept"]
        ts = tasks_by.get(dept, [])
        members = ctx["members"].get(dept, [])
        if not members:
            drift.append(f"名簿(INDEX.md)に所属の記載が無い部屋: {dept}")
        rooms.append(render_room(dept, labels.get(dept) or short_label(c.get("name"), dept), ts, members, ctx))

    unassigned = [t for d, v in tasks_by.items() if d not in known_depts for t in v]
    if unassigned:
        rooms.append(render_room("_unassigned", "未分類(部屋の無いdept)", unassigned, [], ctx))
    if not ok:
        drift.append("D1取得に失敗=タスク状態は『不明』として表示(待機とは表示していない)")
    return rooms, drift


def render_room(dept, label, ts, members, ctx):
    d1_ok = ctx["d1_ok"]
    working = [t for t in ts if t.get("status") == "in_progress"]
    opens = [t for t in ts if t.get("status") == "open"]
    blocked = [t for t in ts if t.get("status") == "blocked"]
    dones = [t for t in ts if t.get("status") == "done"]
    state = bubble_state(ts) if d1_ok else "unknown"

    # 吹き出し: 実データ > 実データ > 演出。実データがある限り演出は出さない。
    extra = ctx["dept_extra"].get(dept)
    pend = ctx["inbox"].get(dept) or (ctx["inbox"].get("_main") if dept == "research-room" else 0)
    if not d1_ok:
        bubble, cls = "❓ D1取得失敗 — タスク状態は不明", "unknown"
    elif blocked:
        bubble, cls = "🛑 " + esc(blocked[0].get("summary"), 40) + f"(承認待ち{len(blocked)}件)", "blocked"
    elif working:
        bubble, cls = "💬 " + esc(working[0].get("summary"), 46), "work"
    elif opens:
        bubble, cls = f"📥 仕事箱に{len(opens)}件", "queue"
    elif pend:
        bubble, cls = f"📬 配達済み未処理 {pend}件", "queue"
    elif extra:
        bubble, cls = "📗 " + extra, "work"
    else:
        bubble, cls = idle_bubble(members, ctx), "idle"

    pres = ctx["presence"].get(dept)
    pres_html = ""
    if pres:
        st, lab, slabel, mt = pres
        title = esc(slabel, 60) if slabel else ""
        pres_html = (f'<span class="pres {st}" title="{title}">{html.escape(lab)}'
                     f'{" / " + epoch_jst(mt) if mt else ""}</span>')

    chips = "".join(member_chip(m, cls, ctx) for m in members) or '<span class="nomember">(名簿未登録)</span>'
    acts = [t.get("completed_at") or t.get("created_at") for t in ts]
    acts += [e.get("created_at") for e in ctx["events"] if normalize_dept(e.get("source_dept")) == dept]
    last_act = jst_str(latest_ts([a for a in acts if a])) or "—"

    rows = ""
    for t in (blocked + working + opens)[:6]:
        rows += f'<li>[{html.escape(str(t.get("status")))}] {esc(t.get("summary"))}</li>'
    for t in dones[:3]:
        rows += (f'<li class="done">✅ {esc(t.get("result") or t.get("summary"))} '
                 f'<span class="ts">{jst_str(t.get("completed_at"))}</span></li>')
    if ctx["dept_detail"].get(dept):
        rows += ctx["dept_detail"][dept]
    if not rows:
        rows = "<li>D1に記録なし</li>" if d1_ok else "<li>D1取得失敗のため不明</li>"

    badges = ""
    if blocked:
        badges += f'<span class="badge bl">承認待ち{len(blocked)}</span>'
    if opens:
        badges += f'<span class="badge op">箱{len(opens)}</span>'
    if pend:
        badges += f'<span class="badge ib">未処理{pend}</span>'
    color = ctx["room_color"](dept)
    return f'''
<details class="room" data-dept="{html.escape(dept)}" style="--room:{color}">
 <summary>
  <div class="rhead"><b>{html.escape(label)}</b>{badges}</div>
  <div class="bubble {cls}">{bubble}</div>
  <div class="chips">{chips}</div>
  <div class="lastact">{pres_html}<span class="la">最終活動: {last_act}</span></div>
 </summary>
 <ul class="tasks">{rows}</ul>
</details>'''


def idle_bubble(members, ctx):
    """タスクが無い時だけ出る演出。**業務状態ではない**ことを明示する(設計書v1 §1)。

    個別表示にするのは「演出を持つ部員が居る部屋」だけ(Chami指定2026-07-14=
    片方の演出が部屋全体の状態に見えるのを防ぐため)。誰も演出を持たない部屋で
    『全員: 待機中』を並べても情報がゼロなので、1行に畳む。
    """
    if not any(ctx["idle_texts"].get(m) for m in members):
        return "🍵 待機中"
    lines = []
    for m in members[:4]:
        acts = ctx["idle_texts"].get(m)
        lines.append(f'{m}: {ctx["rng"].choice(acts)} <i>※演出</i>' if acts else f"{m}: 待機中")
    return "🍵 " + "<br>".join(lines)


def member_chip(name, state, ctx):
    color = ctx["colors"].get(name, "#8899aa")
    sp = pick_sprite(ctx["sprites"].get(name), state if state in ("work", "queue", "blocked", "idle") else "idle",
                     ctx["rng"])
    face, tip = "", name
    if sp:
        img, cat, perf = sp
        tip = f"{name}({cat}{'・演出' if perf else ''})"
        face = (f'<span class="face" style="background:{color} url(../{html.escape(img, quote=True)}) '
                f'center/cover no-repeat"></span>')
    else:
        av = ctx["assets"].get(name)
        if av:
            face = (f'<span class="face" style="background:{color} url({html.escape(av, quote=True)}) '
                    f'center/cover no-repeat"></span>')
        else:
            face = f'<span class="face" style="background:{color}">{html.escape(name[:1])}</span>'
    return f'<div class="chip" title="{html.escape(tip)}">{face}<span class="nm">{html.escape(name)}</span></div>'


# ── HTML ─────────────────────────────────────────────────────────
CSS = """
 :root{--bg:#0e1422;--card:#16203a;--ink:#e8eef7;--accent:#2bb3c0;--cream:#fffdf6;--line:#0a0f1a}
 body{font-family:"Yu Gothic","MS Gothic",monospace;background:var(--bg);color:var(--ink);margin:0;padding:14px}
 h1{color:var(--cream);font-size:18px;margin:2px 0 10px} h1 small{color:#8fa3bd;font-weight:normal;font-size:11px}
 .warn{background:#7a2b2b;color:#fff;border:3px solid var(--line);border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:13px}
 .warn b{color:#ffd7d7}
 .summarybar{background:var(--cream);color:#1b2433;border:3px solid var(--line);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px;display:flex;gap:18px;flex-wrap:wrap}
 .ceo{background:#123040;color:var(--ink);border:3px solid var(--line);border-left:8px solid var(--accent);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px}
 .ceo ul{margin:6px 0 0;padding-left:18px} .ceo li{margin:2px 0}
 .mach{background:#16203a;border:3px solid var(--line);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:12px;display:flex;gap:14px;flex-wrap:wrap;align-items:center}
 .dmn{border:2px solid var(--line);border-radius:6px;padding:1px 6px;background:#1d6b4f}
 .dmn.bad{background:#7a2b2b} .dmn.unk{background:#4a4a4a}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
 .room{background:var(--room,#cfd8e5);color:#1b2433;border:3px solid var(--line);border-radius:8px;padding:10px;box-shadow:4px 4px 0 var(--line)}
 .room summary{cursor:pointer;list-style:none}
 .rhead{display:flex;align-items:center;gap:8px;font-size:14px;margin-bottom:6px}
 .bubble{background:#fff;border:2px solid var(--line);border-radius:10px;padding:5px 9px;font-size:12px;display:inline-block;margin-bottom:8px;max-width:100%}
 .bubble.work{background:#e8f8fa} .bubble.queue{background:#eef4ff} .bubble.blocked{background:#ffe0e0}
 .bubble.unknown{background:#ffe9c7} .bubble.idle{color:#5a6472} .bubble i{color:#8a94a3;font-style:normal;font-size:10px}
 .chips{display:flex;gap:10px;flex-wrap:wrap}
 .chip{text-align:center;font-size:10px}
 .face{display:block;width:34px;height:34px;border:2px solid var(--line);border-radius:6px;margin:0 auto 3px;
        color:#fff;font-size:16px;line-height:32px;text-shadow:1px 1px 0 var(--line)}
 .nomember{font-size:10px;color:#6b7686}
 .lastact{font-size:10px;color:#41506a;margin-top:6px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
 .pres{border:2px solid var(--line);border-radius:6px;padding:0 5px;background:#cfd8e5}
 .pres.active{background:#2bb3c0;color:#04222a} .pres.stale{background:#e6d7b0} .pres.none{background:#c9cfd8;color:#5a6472}
 .badge{font-size:10px;border:2px solid var(--line);border-radius:6px;padding:1px 5px;background:#fff}
 .badge.bl{background:#ffd2d2} .badge.op{background:#d8ecff} .badge.ib{background:#ffe9c7}
 .tasks{font-size:11px;background:#fff;border:2px solid var(--line);border-radius:6px;margin:8px 0 0;padding:8px 8px 8px 24px}
 .tasks .done{color:#2a6b45} .ts{color:#7c8797;font-size:10px}
 .timeline{background:var(--card);border:3px solid var(--line);border-radius:8px;padding:10px;margin-top:14px}
 .timeline h2{font-size:13px;margin:0 0 6px;color:var(--cream)} .timeline ul{margin:0;padding-left:18px;font-size:11px;line-height:1.7}
 .timeline .src{color:var(--accent)}
 footer{color:#7c8797;font-size:10px;margin-top:10px}
"""

JS = """
(function(){
 var GEN=%GEN%*1000;
 function fresh(){
  var age=(Date.now()-GEN)/60000, b=document.getElementById('stale');
  if(age>60){b.style.display='block';
   b.innerHTML='<b>⚠ この画面は '+Math.floor(age/60)+'時間'+Math.floor(age%%60)+'分前のスナップショット</b> — 今の状態ではない。再生成: <code>python scripts/office/build_office.py --open</code>';}
 }
 fresh(); setInterval(fresh,60000);
 var K='office_open_rooms';
 var open=[]; try{open=JSON.parse(localStorage.getItem(K)||'[]')}catch(e){}
 document.querySelectorAll('details.room').forEach(function(d){
  if(open.indexOf(d.dataset.dept)>=0) d.open=true;
  d.addEventListener('toggle',function(){
   var s=[]; document.querySelectorAll('details.room').forEach(function(x){if(x.open)s.push(x.dataset.dept)});
   try{localStorage.setItem(K,JSON.stringify(s))}catch(e){}
  });
 });
})();
"""


def render_html(ctx, rooms, gen_epoch):
    now = ctx["now"]
    ok = ctx["d1_ok"]
    tasks = ctx["tasks"]
    total_open = sum(1 for t in tasks if t.get("status") in ("open", "in_progress")) if ok else "?"
    done_today = sum(1 for t in tasks if is_jst_today(t.get("completed_at"), now)) if ok else "?"
    chg_today = sum(1 for c in ctx["changes"] if is_jst_today(c.get("created_at"), now)) if ok else "?"
    now_jst = to_jst(now).strftime("%Y-%m-%d %H:%M")

    warn = ""
    if not ok:
        warn = (f'<div class="warn"><b>⚠ D1取得失敗 — この画面のタスク・イベントは不完全</b><br>'
                f'{esc(ctx["d1_error"], 200)}<br>'
                f'表示されている『不明』は待機の意味ではない(在席・受信箱・常駐はローカル取得なので有効)</div>')

    inc = ctx["incident"]
    inc_html = f'INC-{inc[0]} ({inc[1]}) {esc(inc[2], 40)}' if inc else "—"

    reqs = [r for r in ctx["reqs"] if str(r.get("status")) in ("proposed", "approved")]
    blocked_all = [t for t in tasks if t.get("status") == "blocked"]
    ceo_items = ""
    for r in reqs[:6]:
        ceo_items += (f'<li><b>{esc(r.get("req_code"), 12)}</b> [{esc(r.get("status"), 10)}] '
                      f'{esc(r.get("department"), 16)} — {esc(r.get("problem"), 60)}</li>')
    for t in blocked_all[:6]:
        ceo_items += f'<li>🛑 {esc(t.get("assigned_dept"), 16)} — {esc(t.get("summary"), 60)}</li>'
    if not ceo_items:
        ceo_items = "<li>承認待ちなし" + ("" if ok else "(D1取得失敗のため不明)") + "</li>"

    dmn, dmn_at = ctx["daemons"]
    dmn_html = "".join(
        f'<span class="dmn {"" if s == "ok" else ("unk" if s in ("start", "restart") else "bad")}">{html.escape(n)}: {html.escape(s)}</span>'
        for n, s in dmn) or '<span class="dmn unk">常駐ログなし</span>'

    tl = []
    for e in ctx["events"]:
        tl.append((e.get("created_at"), "dept_events", esc(e.get("source_dept"), 18),
                   f'{esc(e.get("event_type"), 28)} — {esc(e.get("summary"), 60)}'))
    for g in ctx["git"]:
        tl.append((g["ts"], "git", g["hash"], esc(g["subject"], 70)))
    tl.sort(key=lambda x: (to_jst(x[0]) or to_jst("1970-01-01 00:00:00")), reverse=True)
    tl_html = "".join(f'<li><span class="ts">{jst_str(t[0])}</span> <span class="src">[{t[1]}]</span> '
                      f'<b>{t[2]}</b> {t[3]}</li>' for t in tl[:24]) or "<li>記録なし</li>"

    doc = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>go5 AIオフィス</title>
<style>{CSS}</style></head><body>
<h1>🏢 go5-maker AIオフィス <small>偽Status禁止=表示は全て実データ / 生成 {now_jst} JST</small></h1>
<div class="warn" id="stale" style="display:none"></div>
{warn}
<div class="summarybar"><span>📥 未完了: <b>{total_open}</b></span><span>✅ 本日完了(JST): <b>{done_today}</b></span>
 <span>🔧 本日のCHG(JST): <b>{chg_today}</b></span><span>🚨 最新: {inc_html}</span></div>
<div class="ceo">👑 <b>CEO室 — Chami</b>: あなた待ちの案件<ul>{ceo_items}</ul></div>
<div class="mach"><b>⚙ 機械室(常駐)</b>{dmn_html}<span class="ts">最終確認: {epoch_jst(dmn_at) or "—"}</span></div>
<div class="grid">{"".join(rooms)}</div>
<div class="timeline"><h2>📜 タイムライン(dept_events + git log)</h2><ul>{tl_html}</ul></div>
<footer>ローカル専用・非公開 / 再生成: python scripts/office/build_office.py --open /
 在席は3状態(在席=脈あり / 脈なし=不在または処理中[INC-94: 配達の瞬間に脈が止まるため断定しない] / 未計測) /
 待機演出はキャラ設定由来の装飾で業務状態ではない</footer>
<script>{JS.replace("%GEN%", str(int(gen_epoch)))}</script>
</body></html>'''
    return doc


# ── main ─────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="AIオフィス生成")
    ap.add_argument("--open", action="store_true", help="生成後に開く")
    ap.add_argument("--no-net", action="store_true", help="アバターを取りに行かない(キャッシュのみ)")
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    now_epoch = datetime.datetime.now(datetime.timezone.utc).timestamp()
    report = []

    d1_ok, d1, d1_err = fetch_d1(D1_QUERIES)
    if not d1_ok:
        print(f"⚠ D1取得失敗: {d1_err}")

    tasks = d1.get("tasks", [])
    channels = load_channels()
    members = load_membership()
    colors = load_colors()
    avatars = load_avatars()
    sprites = normalize_sprites(read_json(os.path.join(LOCAL, "persona_sprites.json"), {}))
    idle_texts = load_idle_texts()

    assets = {}
    if not args.no_net:
        for name, url in avatars.items():
            got = localize_asset(url, report)
            if got:
                assets[name] = got

    # 部門別の実データ(実仕事の正本が dept_tasks でない部門=学習室・コピー部・研究室)
    dept_extra, dept_detail = {}, {}
    lq = d1.get("learning", [])
    if lq:
        un = [q for q in lq if not q.get("answered_at")]
        dept_extra["learning-coach"] = f'学習Q {len(lq)}件記録(未回答{len(un)})'
        dept_detail["learning-coach"] = "".join(
            f'<li>📗 {esc(q.get("topic"), 20)} — {esc(q.get("question_text"), 50)} '
            f'<span class="ts">{jst_str(q.get("created_at"))}</span></li>' for q in lq[:3])
    cr = d1.get("copy", [])
    if cr:
        dept_extra["copy-director"] = f'コピー改稿 {len(cr)}件'
        dept_detail["copy-director"] = "".join(
            f'<li>📗 [{esc(c.get("field"), 12)}] {esc(c.get("final_text"), 50)} '
            f'<span class="ts">{jst_str(c.get("created_at"))}</span></li>' for c in cr[:3])
    rn = d1.get("research", [])
    if rn:
        dept_extra["research-room"] = f'研究メモ {len(rn)}件'
        dept_detail["research-room"] = "".join(
            f'<li>📗 {esc(n.get("topic"), 40)} [{esc(n.get("status"), 10)}] '
            f'<span class="ts">{jst_str(n.get("created_at"))}</span></li>' for n in rn[:3])

    def room_color(dept):
        ms = members.get(dept) or []
        for m in ms:
            c = colors.get(m)
            if c and c.upper() != "#FFFFFF":
                return c + "44"                      # キャラ色を薄く敷く(部屋の識別色)
        return "#cfd8e5"

    ctx = {
        "now": now, "cfg": load_rooms_config(), "channels": channels, "members": members,
        "colors": colors, "assets": assets, "sprites": sprites, "idle_texts": idle_texts,
        "tasks": tasks, "events": d1.get("events", []), "changes": d1.get("changes", []),
        "reqs": d1.get("reqs", []), "d1_ok": d1_ok, "d1_error": d1_err,
        "presence": load_presence(now_epoch), "inbox": load_inbox_counts(),
        "daemons": load_daemons(), "git": load_git_log(), "incident": load_latest_incident(),
        "dept_extra": dept_extra, "dept_detail": dept_detail, "room_color": room_color,
        # 同じ入力なら同じ出力にする(F7: 無シードだと再生成のたび無意味な差分が出る)
        "rng": random.Random(to_jst(now).strftime("%Y-%m-%d")),
    }

    rooms, drift = build_rooms(ctx)
    doc = render_html(ctx, rooms, now_epoch)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)

    print(f"生成: {OUT} (部屋{len(rooms)} / タスク{len(tasks)}件 / 在席{sum(1 for v in ctx['presence'].values() if v[0] == 'active')}窓)")
    for d in drift + report:
        print("  ・" + d)
    if args.open:
        try:
            if sys.platform.startswith("win"):
                os.startfile(OUT)                    # noqa: S606
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", OUT], check=False)
        except Exception as e:
            print(f"  ・開けなかった(パスを直接開いてくれ): {e}")
    return 0 if d1_ok else 1                          # 失敗は終了コードにも出す(自動化から検知可能に)


if __name__ == "__main__":
    sys.exit(main())
