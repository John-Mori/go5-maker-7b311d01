#!/usr/bin/env python3
"""AIオフィス 純粋関数層(I/O・ネットワークなし=テスト可能)。

設計: docs/設計・調査/AIオフィス_部屋型_改善書_v1.md (K-11: 導出ロジックを純粋関数へ切り出す)
テスト: python tests/test_office.py

ここに置くもの: 時刻の解釈・部門slugの正規化・在席状態の判定・立ち絵の選択・
                名前の名寄せ・バブル状態の導出。**全て入力→出力が決まる関数**。
ここに置かないもの: D1呼び出し・ファイル読み書き・HTML生成(=build_office.py)。

大原則(設計書v1): 偽Status禁止。実データが無い時に「それらしい状態」を作らない。
"""
import datetime
import html
import re

# ── 部門slugの正規化 ────────────────────────────────────────────────
# D1に残る旧slug・日本語キーを現行の正規語彙(agent名=discord_channels.jsonのdept)へ寄せる。
# 正規語彙の定義元: docs/departments/00_common/orchestration.md
DEPT_ALIASES = {
    "dev": "system-engineer",          # 組織化以前の旧slug(D1に11件実在)
    "kaizen": "kaizen-analyst",        # 部門名確定前の旧slug(D1に1件実在)
    "司令塔": "research-room",          # 旧ROSTERの日本語キー(どの台帳とも噛み合わない)
    "研究室": "research-room",
    "incident-recovery": "incident",   # INDEX.mdの表記 → チャンネル台帳のslug
}


def normalize_dept(slug):
    """部門slugを正規語彙へ。未知はそのまま返す(捨てない=取りこぼし検知のため)。"""
    s = (slug or "").strip()
    return DEPT_ALIASES.get(s, s)


# ── 名前の名寄せ ──────────────────────────────────────────────────
# 台帳ごとの表記ゆれを1つの正規名へ(ORG-8: 完全一致依存の脆さ対策)。
NAME_ALIASES = {
    "ケヴィン・デブライネ": "デブライネ",
    "ケヴィン・デ・ブライネ": "デブライネ",
    "デ・ブライネ": "デブライネ",
    "オタコン(ハル・エメリッヒ)": "オタコン",
    "クラウディア・バレンツ": "クラウディア",
    "ルカ・モドリッチ": "モドリッチ",
    "ソリッド・スネーク": "スネーク",
    "中野五月(なかのいつき)": "中野五月",
}


def canon_name(name):
    """表示名を台帳照合用の正規名へ。括弧の補足・兼任印を落として別名表を引く。

    例: 'オタコン(兼)' → 'オタコン' / 'ケヴィン・デブライネ' → 'デブライネ'
        'アメス(補佐)' → 'アメス' / '田中琴葉(記録・構造化=兼任)' → '田中琴葉'
    """
    s = (name or "").strip()
    s = re.sub(r"\*\*", "", s)            # markdown強調を除去
    s = s.strip()
    if s in NAME_ALIASES:                  # 括弧ごと一致する別名(オタコン(ハル・エメリッヒ)等)を先に
        return NAME_ALIASES[s]
    s = re.sub(r"[(（][^)）]*[)）]", "", s)  # 残りの括弧補足を除去
    s = s.strip(" 　*")
    return NAME_ALIASES.get(s, s)


# ── 時刻(UTC↔JST) ────────────────────────────────────────────────
JST = datetime.timezone(datetime.timedelta(hours=9))


def parse_ts(ts):
    """D1やログの時刻文字列を **naive UTC** のdatetimeへ。解釈できなければNone。

    受ける形: 'YYYY-MM-DD HH:MM:SS' / ISO('T'・小数秒・'Z') / '+09:00'等のオフセット付き /
              epoch秒・ミリ秒(数値または数字文字列)。
    オフセット付きは実際のUTC時刻へ換算する(F6: 従来は+9h二重加算していた)。
    """
    if ts is None or ts == "":
        return None
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo:
            return ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return ts
    # epoch(数値・数字文字列)
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and re.fullmatch(r"\d{9,14}", ts.strip())):
        v = float(ts)
        if v > 1e12:      # ミリ秒
            v /= 1000.0
        try:
            return datetime.datetime.fromtimestamp(v, datetime.timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        # 最後の手掛かり: 先頭19文字が 'YYYY-MM-DD HH:MM:SS' 形なら拾う
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", s)
        if not m:
            return None
        try:
            dt = datetime.datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
        except ValueError:
            return None
    if dt.tzinfo:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def to_jst(ts):
    """naive UTC前提の入力をJSTのdatetimeへ。解釈不能ならNone。"""
    dt = parse_ts(ts)
    if dt is None:
        return None
    return dt.replace(tzinfo=datetime.timezone.utc).astimezone(JST)


def jst_str(ts, fmt="%m/%d %H:%M"):
    """表示用のJST文字列。解釈できない値は **生のまま出さず** 空文字にする。

    (F6: 従来は数値epochが生の数字列のまま画面に出ていた)
    """
    j = to_jst(ts)
    return j.strftime(fmt) if j else ""


def jst_date_str(ts):
    """そのタイムスタンプのJSTでの暦日 'YYYY-MM-DD'。解釈不能なら空。"""
    j = to_jst(ts)
    return j.strftime("%Y-%m-%d") if j else ""


def is_jst_today(ts, now_utc):
    """JSTの暦日で「今日」か(F3: 従来はUTC暦日で数え、JST 0-9時の分が消えていた)。"""
    d = jst_date_str(ts)
    return bool(d) and d == jst_date_str(now_utc)


def latest_ts(values):
    """時刻値の集合から最新を返す(パースして比較=文字列maxの書式混在誤判定を避ける)。

    F6: 'T'区切りとスペース区切りが混在すると文字列比較は 'T'(0x54) > ' '(0x20) で誤る。
    """
    best, best_dt = "", None
    for v in values:
        dt = parse_ts(v)
        if dt and (best_dt is None or dt > best_dt):
            best, best_dt = v, dt
    return best


# ── 在席(セッションの脈) ──────────────────────────────────────────
# 閾値の前例: scripts/discord/inbox_poller.py の RESIDENT_FRESH_SEC(=600秒・INC-86で90→600)
PRESENCE_FRESH_SEC = 600

# ★INC-94(インシデント.md): waiterの脈は「新着を配達した瞬間」に止まる。
#   つまり脈が古い窓は『不在』かもしれないし『働いている最中』かもしれない——判別できない。
#   ここで「脈なし=不在」と言い切ると、丁寧に仕事をしている窓ほど不在と偽表示される(=偽Status)。
#   よって3状態を**正直に**分ける。断定できないものは断定しない。
PRESENCE_LABEL = {
    "active": "在席(チャイム待機中)",
    "stale": "脈なし(不在または処理中)",
    "none": "未計測(脈ファイルなし)",
}


def presence_state(mtime, now, fresh_sec=PRESENCE_FRESH_SEC):
    """脈ファイルのmtime(epoch)と現在時刻(epoch)から在席状態を返す。

    'active' = 脈が新鮮(waiterが打っている=チャイム待機中)
    'stale'  = 脈が古い(不在 or 処理中。**判別不能なので断定しない**=INC-94)
    'none'   = 脈ファイルが無い(その窓は計測対象外)
    """
    if mtime is None:
        return "none"
    return "active" if (now - mtime) < fresh_sec else "stale"


# ── バブル(頭上の吹き出し)の状態導出 ──────────────────────────────
def bubble_state(tasks):
    """部屋のタスク群から表示状態を導出。実データのみが根拠(偽Status禁止)。

    'blocked' > 'work' > 'queue' > 'idle' の優先順。tasksは status キーを持つdictの列。
    """
    st = [t.get("status") for t in tasks]
    if "blocked" in st:
        return "blocked"
    if "in_progress" in st:
        return "work"
    if "open" in st:
        return "queue"
    return "idle"


# ── 立ち絵(sprites)台帳 ───────────────────────────────────────────
# 台帳スキーマが3形式混在している(SPR-5)ため、消費側は必ずここを通す。
#   (1) 素の文字列        "persona_sprites/kukuru/IMG_1047.png"
#   (2) {label,when,img}  意図別カテゴリ(imgがnull=画像未提供の予約枠あり)
#   (3) {file,src,added}  オタコンのみ・キー名がimgでなくfile・パスに persona_sprites/ が無い
def normalize_sprite_entry(entry):
    """台帳の1エントリを {'img','label','when'} へ正規化。画像が無い枠はNone。

    パスは **local/ 基準** ('persona_sprites/<char>/<file>') に統一して返す。
    """
    if entry is None:
        return None
    if isinstance(entry, str):
        img, label, when = entry, "", ""
    elif isinstance(entry, dict):
        img = entry.get("img") or entry.get("file")
        label = entry.get("label") or ""
        when = entry.get("when") or ""
    else:
        return None
    if not img:
        return None                       # 画像未提供の予約枠(琴葉rare等)は「無い」として扱う
    img = str(img).replace("\\", "/").lstrip("./")
    if not img.startswith("persona_sprites/"):
        img = "persona_sprites/" + img    # (3)オタコン形式のパス基準を吸収
    return {"img": img, "label": label, "when": when}


def normalize_sprites(ledger):
    """立ち絵台帳全体を {キャラ正規名: {カテゴリ: [正規化エントリ,…]}} へ。

    _meta と、role/traits_note等の非カテゴリキーは落とす。空カテゴリは持たない。
    """
    out = {}
    for name, body in (ledger or {}).items():
        if name == "_meta" or not isinstance(body, dict):
            continue
        cats = {}
        for cat, val in body.items():
            if not isinstance(val, list):
                continue                   # role/traits_note/note/reading 等は対象外
            items = [normalize_sprite_entry(e) for e in val]
            items = [i for i in items if i]
            if items:
                cats[cat] = items
        if cats:
            out[canon_name(name)] = cats
    return out


# 状態→立ち絵カテゴリの写像。**出し分けの根拠は実status**なので偽Status禁止と両立する。
# 演出カテゴリ(rare/mischief)は idle 時のみ・かつ「演出」と明示する(設計書v1 §1の原則)。
SPRITE_FOR_STATE = {
    "work": ["talking", "insight", "normal"],
    "queue": ["normal"],
    "blocked": ["emergency", "flustered", "normal"],
    "idle": ["resting", "rare", "mischief", "normal"],
}
PERFORMANCE_CATS = {"rare", "mischief"}   # 業務状態ではない=「演出」と明示する対象


def pick_sprite(cats, state, rng):
    """状態に合う立ち絵を1枚選ぶ。無ければNone。

    戻り値: (img_path, category, is_performance) / None
    rng は random.Random 互換(seed済みを渡す=同じ入力なら同じ絵=F7)。
    """
    if not cats:
        return None
    for cat in SPRITE_FOR_STATE.get(state, ["normal"]):
        items = cats.get(cat)
        if items:
            e = rng.choice(items)
            return (e["img"], cat, cat in PERFORMANCE_CATS)
    return None


# ── idle演出テキスト(正本=persona_manifest.yml) ──────────────────
def parse_idle_text(idle_field):
    """manifestのidle行から実際の演出テキストだけを取り出す。

    例: '待機中の特殊演出(稀に発生・おまけ)=自主トレ中'      → ['自主トレ中']
        '待機中の特殊演出(稀・おまけ)=野良猫と会話中 / 昼寝中' → ['野良猫と会話中','昼寝中']
    """
    s = (idle_field or "").strip()
    if not s:
        return []
    if "=" in s:
        s = s.split("=", 1)[1]
    return [x.strip() for x in s.split("/") if x.strip()]


# ── 表示ヘルパ ────────────────────────────────────────────────────
def esc(s, n=70):
    """切り詰めてからHTMLエスケープ(順序が逆だと実体参照が途中で割れる)。"""
    s = str(s or "")
    return html.escape(s[:n] + ("…" if len(s) > n else ""))
