#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""close_request — 実依頼(C-023の--work便 / requests.jsonl)を「完了/済/close」にする
唯一の認可経路。閉じる前に実物ポインタを1つ機械照合し、通らなければ閉じない(=依頼を生かす)。

★C-024(2026-07-31・種:アメス / HQ発注 DISPATCH-aegis-gl-1785425181305):
  受領印は付くのに実体が作られない「偽受領」が、依頼元に毎回自分で検証させ、
  Chamiが委任を手放せない根因になっていた。→ close だけにゲートをかける。

線引き(fail-openを壊さない):
  ・👀(読んだ)/✅(着手)は実物不要=react.py のまま。ここでは一切触らない。
  ・ゲートは「完了/済/close」操作だけにかける。
  ・判定不能は「喋る側=依頼を開いたまま残す側」へ倒す(closeを拒否・依頼は生かす)。

照合材料(どれか1つ実在すれば通す。HQ指定):
  ・生成ファイルの実在(パス)
  ・msg_idリンクの実在(work_audit.jsonl に観測がある=その便が実処理された)
  ・commit の実在(git cat-file -e)

使い方:
  python scripts/llm/close_request.py --req "<open な req の部分一致>" \
      --proof "scripts/llm/close_request.py" --done "ゲート新設" --dept aegis-gl
  python scripts/llm/close_request.py --proof "1785336943411" --verify-only   # 照合だけ試す

★これは新規追加のみ(既存の requests.jsonl の読み手=daily_report.py / 起動時読み上げは
  status=='closed' を今までどおり除外するだけ)。送信合流点・relay・dispatch には触らない。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
REQUESTS = os.path.join(LOCAL, "requests.jsonl")
AUDIT = os.path.join(LOCAL, "llm", "work_audit.jsonl")

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.I)
_MSGID_RE = re.compile(r"^[0-9A-Za-z._-]{6,}$")


def _norm_candidates(proof, root=ROOT):
    """work_audit の ~ / ~.. プレフィックスや \\ 混じりも吸収して、実在チェック用の候補パスを返す。"""
    p = proof.strip().strip('"').strip("'")
    p = p.lstrip("~")                 # ~local\... / ~..\... の先頭 ~ を落とす
    p = p.replace("\\", "/")
    cands = []
    if os.path.isabs(p):
        cands.append(p)
    cands.append(os.path.normpath(os.path.join(root, p)))
    cands.append(os.path.normpath(os.path.join(root, "..", p)))
    # 重複除去(順序保持)
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def _proof_in_audit(proof, audit_path=AUDIT):
    """msg_id が work_audit.jsonl に観測されているか(=その便が実処理された)。"""
    if not os.path.exists(audit_path):
        return False
    needle = proof.strip()
    try:
        for line in open(audit_path, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                if needle in line:      # 壊れ行でも文字列一致は拾う(fail-openより厳しく実在側)
                    return True
                continue
            if rec.get("msg_id") == needle:
                return True
            # touched の中に生成物として現れるケースも実在扱い
            for t in rec.get("touched", []) or []:
                if needle in str(t):
                    return True
    except Exception:
        return False
    return False


def _commit_exists(proof, root=ROOT):
    if not _COMMIT_RE.match(proof.strip()):
        return False
    try:
        r = subprocess.run(["git", "cat-file", "-e", proof.strip() + "^{commit}"],
                           cwd=root, capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def verify_proof(proof, root=ROOT, audit_path=AUDIT):
    """実物ポインタが1つでも実在するか機械照合する(純粋関数=単体テスト可)。
    戻り: (ok: bool, kind: str, detail: str)。ok=False は「閉じてはいけない」。"""
    if not proof or not proof.strip():
        return (False, "none", "proof が空=照合材料なし")
    proof = proof.strip()

    # 1) ファイル実在
    for c in _norm_candidates(proof, root):
        if os.path.exists(c):
            return (True, "file", c)

    # 2) commit 実在
    if _commit_exists(proof, root):
        return (True, "commit", proof)

    # 3) work_audit に観測されている(msg_id の実在、または touched 生成物の観測)
    #    ★パス形/msg_id形の両方を拾う=HQ指定の「work_audit.jsonl の観測」。
    #    誤検出を避けるため6文字未満の断片は照合材料にしない。
    if len(proof) >= 6 and _proof_in_audit(proof, audit_path):
        return (True, "observed", f"observed in {os.path.basename(audit_path)}")

    return (False, "unverified", f"'{proof}' はファイル/commit/observed-msg_id のどれにも実在しなかった")


def find_open_requests(query, path=REQUESTS):
    """req に query を部分一致で含む open な依頼を返す(query 空なら open 全件)。"""
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("status") == "closed":
            continue
        if query and query not in (rec.get("req") or ""):
            continue
        out.append(rec)
    return out


def append_closed(rec, path=REQUESTS):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description="実依頼を実物照合してから閉じる(C-024ゲート)")
    ap.add_argument("--req", default="", help="閉じたい open な req の部分一致キー")
    ap.add_argument("--proof", default="", help="実物ポインタ(パス / commit / observed msg_id)")
    ap.add_argument("--done", default="", help="完了の一行説明(done欄へ)")
    ap.add_argument("--dept", default="", help="閉じた部門")
    ap.add_argument("--msg-id", default="", help="C-023 --work便のmsg_id(記録に残す・任意)")
    ap.add_argument("--verify-only", action="store_true", help="照合だけ試して閉じない")
    ap.add_argument("--dry-run", action="store_true", help="照合は本番・書き込みだけしない")
    a = ap.parse_args()

    ok, kind, detail = verify_proof(a.proof)
    print(f"[照合] proof={a.proof!r} → {'OK' if ok else 'NG'} kind={kind} ({detail})")

    if a.verify_only:
        sys.exit(0 if ok else 2)

    if not ok:
        print("  ✗ close 拒否=実物が照合できない。依頼は open のまま残す(fail toward open)。", file=sys.stderr)
        print("    → 実物(生成ファイル/commit/観測済msg_id)を1つ添えて再実行するか、依頼を開いたままにする。", file=sys.stderr)
        sys.exit(2)

    # 閉じる対象の特定(任意=req指定が無ければ記録のみ closed 追記)
    target = None
    if a.req:
        matches = find_open_requests(a.req)
        if len(matches) == 0:
            print(f"  ! open な req に '{a.req}' が一致しない(既にclosed/未起票の可能性)。記録のみ追記する。")
        elif len(matches) > 1:
            print(f"  ✗ '{a.req}' が open {len(matches)}件に一致=特定不能。もっと絞って再実行。", file=sys.stderr)
            for m in matches:
                print("     -", (m.get("req") or "")[:70], file=sys.stderr)
            sys.exit(3)
        else:
            target = matches[0]

    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "from": a.dept or (target or {}).get("from") or "",
        "req": (target or {}).get("req") or a.req or (a.msg_id and f"msg:{a.msg_id}") or "",
        "status": "closed",
        "src": "close_request",
        "done": a.done,
        "proof": a.proof,
        "proof_kind": kind,        # file / commit / msg_id
        "verified": True,          # ★C-024ゲートを通った印
        "msg_id": a.msg_id or "",
    }

    if a.dry_run:
        print("  [dry-run] 追記する内容:", json.dumps(rec, ensure_ascii=False))
        sys.exit(0)

    append_closed(rec)
    print(f"  ✓ closed 追記(検証済 kind={kind})→ {os.path.relpath(REQUESTS, ROOT)}")


if __name__ == "__main__":
    main()
