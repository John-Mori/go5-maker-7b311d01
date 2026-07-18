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
            line = line.strip()
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
