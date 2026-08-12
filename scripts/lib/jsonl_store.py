#!/usr/bin/env python3
"""検証付きJSONL追記ヘルパー(恒久解C1・改善設計書§恒久解C)。

なぜ必要か: 台帳に ts='t' の壊れた行が実在した(接続テストの残骸・2026-07-17実測)。
文字列比較で 't' > '2' となり、テスト残骸が「最新の発言」として知識パックを占領した。
壊れ値は**書き込む側の入口で**弾くのが恒久策(読む側が毎回防御するのは漏れる)。

依存ゼロ(jsonschemaを入れない): このプロジェクトはvanilla方針。標準ライブラリだけで
「型・必須・ISO日時」を検証する軽量バリデータを持つ。設計書は例として jsonschema を
挙げたが、実装では依存を増やさない判断(pip不要=どのセッションでも同じに動く)。

使い方:
  from jsonl_store import append_jsonl, validate, SCHEMAS
  append_jsonl("local/corpus/chami.jsonl", rec, SCHEMAS["corpus"])   # 不正なら ValueError
  ok, errs = validate(rec, SCHEMAS["corpus"])                        # 例外を使わず判定だけ
"""
import datetime as dt
import io
import json
import os
import re

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?")


def _is_iso_ts(v):
    """ISO 8601 の日時か。't' や空や日付だけを弾く。"""
    if not isinstance(v, str) or not _ISO.match(v):
        return False
    try:
        dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


_TYPES = {
    "str": str, "int": int, "float": (int, float), "bool": bool,
    "list": list, "dict": dict, "any": object,
}


def validate(rec, schema):
    """レコードをスキーマで検証。戻り値: (ok, errors)。

    schema = {field: {"type": "str"|..., "required": bool, "format": "iso-ts"|None, "nullable": bool}}
    未知フィールドは許容する(スキーマ進化に強くする=schema-on-readの緩さを残す)。
    """
    errs = []
    if not isinstance(rec, dict):
        return False, ["record is not an object"]
    for field, spec in schema.items():
        required = spec.get("required", False)
        if field not in rec:
            if required:
                errs.append(f"{field}: required but missing")
            continue
        v = rec[field]
        if v is None:
            if not spec.get("nullable", False) and required:
                errs.append(f"{field}: null not allowed")
            continue
        want = spec.get("type", "any")
        pytype = _TYPES.get(want, object)
        if want != "any" and not isinstance(v, pytype):
            errs.append(f"{field}: expected {want}, got {type(v).__name__}")
            continue
        if spec.get("format") == "iso-ts" and not _is_iso_ts(v):
            errs.append(f"{field}: not an ISO datetime (got {v!r})")
    return (len(errs) == 0), errs


def append_jsonl(path, rec, schema=None):
    """1レコードを検証して追記。スキーマ違反は ValueError(書かない)。

    追記は既存コードと同じ素の open(..,'a')。ここが恒久解Cの「入口」で、
    以後この関数を通す書き手は壊れ行を作れなくなる。
    """
    if schema is not None:
        ok, errs = validate(rec, schema)
        if not ok:
            raise ValueError(f"jsonl schema violation for {os.path.basename(path)}: {'; '.join(errs)}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with io.open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


_JST = dt.timezone(dt.timedelta(hours=9))


def ts_epoch(v, default=None):
    """台帳の ts を**epoch秒**にする。帯(タイムゾーン)の有無を取り違えない。

    なぜ要るか(2026-08-13 実測・イージス研究室)=
      同じ台帳の中で ts の書き方が割れている。`change_log.jsonl` 707行の内訳は
      帯つき`+09:00` 664 / 帯なし 29 / **`Z`(UTC) 6** / 空白区切り等 7 / 壊れ 1。
      ★`Z` の6行は**9時間ずれる**= 「直近24時間」の集計で別の日に落ちる。
      各所が自前の `_parse_ts` を持つと**読み方が3通りに割れる**ので、ここ1本に寄せる。

    - 帯つき(`+09:00` / `Z`)= その帯で解釈する(Zは+9してJSTへ揃う)。
    - 帯なし= **JSTとみなす**(このプロジェクトの記録は全部JSTで書かれている)。
    - `T` の代わりに空白のもの・秒が無いものも受ける。
    - 読めない値は `default` を返す(★黙って0にしない= 1970年扱いで集計に混ざるのを防ぐ)。
    """
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return default
    s = v.strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if not _ISO.match(s):        # 日付だけ・'t' 等は弾く(_is_iso_ts と同じ厳しさに揃える)
        return default
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        try:                                    # 秒やミリ秒の端が汚れている時の救済
            d = dt.datetime.fromisoformat(s[:19])
        except ValueError:
            return default
    if d.tzinfo is None:
        d = d.replace(tzinfo=_JST)
    return d.timestamp()


def read_jsonl(path, schema=None, on_bad="skip"):
    """JSONLを読む。schema指定時は不正行を on_bad で扱う('skip'=飛ばす/'raise'=例外)。

    既存ファイルには壊れ行が実在するので、読む側の防御としても使える。
    戻り値: (rows, bad) — badは (行番号, 理由) のリスト。
    """
    rows, bad = [], []
    if not os.path.exists(path):
        return rows, bad
    with io.open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            # ★BOM(﻿)を落とす(2026-08-13 実測・イージス研究室)=
            #   change_log.jsonl の**1行目**に BOM が付いていて、json.loads が
            #   「Expecting value」で落ち、**dept=system-engineer の実記録1件が
            #   どの読み手からも永久に見えなかった**(commit 1b4aa38 / 2026-07-22)。
            #   PowerShell の Out-File/`>` は既定でBOM付きUTF-8を書く=**また起きる**。
            #   行ごとに落とすので、追記で途中に混ざった場合も拾える。
            line = line.strip().lstrip("﻿").strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                bad.append((i, f"invalid json: {e}"))
                if on_bad == "raise":
                    raise
                continue
            if schema is not None:
                ok, errs = validate(rec, schema)
                if not ok:
                    bad.append((i, "; ".join(errs)))
                    if on_bad == "raise":
                        raise ValueError(f"line {i}: {errs}")
                    continue
            rows.append(rec)
    return rows, bad


# うちの主要台帳のスキーマ(既知フィールドのみ。未知は許容)。
SCHEMAS = {
    "corpus": {
        "ts": {"type": "str", "required": True, "format": "iso-ts"},
        "msg_id": {"type": "str", "required": True},
        "content": {"type": "str", "required": True},
        "sensitive": {"type": "bool", "required": False},
    },
    "lessons": {
        "ts": {"type": "str", "required": True, "format": "iso-ts"},
        "verdict": {"type": "str", "required": True},
        "source_key": {"type": "str", "required": False},
    },
    "responder_log": {
        "ts": {"type": "str", "required": True, "format": "iso-ts"},
        "mode": {"type": "str", "required": False},
    },
}
