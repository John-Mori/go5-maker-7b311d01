# -*- coding: utf-8 -*-
"""PreToolUse フック= 作業ツリーを壊すgitコマンドを、機構として止める。

★作った理由(2026-08-29・研究室HQ)
  起動文には「不可逆・削除は上げてから」と**文章で**書いてあるだけで、機構が無かった。
  全部門共通規律 §3「心がけに任せない。機構に載せる」を、我々自身が破っていた。
  実害の履歴もある= 並列gitが作業ツリーを壊した / ステージが他セッションのcommitに吸われた /
  untrackedが消えた。どれも「気をつける」では二度目が来る。

止めるもの(実際に事故を起こした形だけ。広げない)
  git reset --hard / git clean -f / git checkout -- <path> / git push --force / git branch -D
  ★`--force-with-lease` は通す(壊れにくい形なので、安全な方へ誘導する)。
  ★`rm -rf` は**入れていない**= うちの事故履歴に無く、ビルドの掃除で日常的に使う部屋がある。
    常に誤発火する安全網は無視される(共通規律 §3)。

★fail-open= このフック自身が壊れても作業は止めない(判定できない時は通す)。
  可用性に関わる所は喋る側へ倒す(共通規律 §3)。最悪の事故は沈黙。

出口
  exit 0 … 通す
  exit 2 … 止める(stderr の文言がモデルへ渡る)。allow ルールより強い。

手で試す
  echo '{"tool_name":"Bash","tool_input":{"command":"git reset --hard HEAD"}}' | python scripts/hooks/guard_destructive.py ; echo $?
"""
import json
import re
import sys

# ★2026-08-29 追加(イージス研究室)= 止めた理由の文言が読めない事故の修理。
#   Windowsの既定は cp932。止めた時に stderr へ書く日本語がcp932で出て、
#   受け手(ハーネス)はUTF-8で読むため**警告文が全部化けた**(実測=下の初回発火)。
#   読めない警告は「なぜ止まったか」を伝えないので、機構としては半分死ぬ。
#   ★reconfigure自体が使えない環境でも止めない= 例外は握って進む(fail-open)。
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ★1件1行。(正規表現, 止めた時に何をすべきか)
_RULES = [
    (r"\bgit\b(?:\s+-C\s+\S+)?\s+reset\b[^|;&]*--hard",
     "作業ツリーが消える。退避なら `git stash` か `git branch <名前>` を使え。"),
    (r"\bgit\b(?:\s+-C\s+\S+)?\s+clean\b[^|;&]*\s-\w*f",
     "未追跡ファイルはgitから救えない(会話履歴しか復元源が無い)。消す前に必ずcommitしろ。"),
    (r"\bgit\b(?:\s+-C\s+\S+)?\s+checkout\b\s+--\s",
     "そのパスの編集内容が消える。残すなら先にcommitしろ。"),
    (r"\bgit\b(?:\s+-C\s+\S+)?\s+push\b[^|;&]*(?:--force(?!-with-lease)|\s-f\b)",
     "originの履歴を壊す。どうしても要るなら `--force-with-lease` を使い、Chamiへ上げてから。"),
    (r"\bgit\b(?:\s+-C\s+\S+)?\s+branch\b[^|;&]*\s-D\b",
     "未マージのブランチが消える。`-d`(安全な削除)で通るか先に試せ。"),
]


# ★2026-08-29 追加(イージス研究室)= 「書いてあるだけ」で止まる誤発火の修理。
#   実測した事故= このフックの受け入れ試験を書こうとしたら、テスト用の**文字列リテラル**
#   ("git reset --hard HEAD")を含むというだけで起動そのものが止まった。同様に
#   `echo 'git clean -fd は危ない' >> docs/note.md`(ただの文書更新)も止まった。
#   常に誤発火する安全網は無視される(共通規律 §3)= 実行されない文脈は判定から外す。
#   ★線引き= 「引用の中に危険コマンドを書いて実行する形」(bash -c "git reset --hard")は
#     うちの事故履歴に無い。このフックの方針(実際に事故を起こした形だけ・広げない)と揃える。
#     ただし**シェルへ食わせるヒアドキュメントだけは例外**=あれは実行される。
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1\s*\n(.*?)\n[ \t]*\2", re.S)
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"", re.S)
_SHELL_SINK = re.compile(r"\b(?:ba|z|k)?sh\b(?:\s+-\w+)*\s*$")


def _blank(m, keep_len=True):
    """位置がずれないよう、同じ長さの空白へ潰す。"""
    s = m.group(0)
    return " " * len(s) if keep_len else " "


def mask_inert(cmd):
    """実行されない文脈(ヒアドキュメント本体・引用の中)を空白へ潰して返す。

    ★fail-open ではなく fail-same= 潰しに失敗したら元の文字列を返すだけ
      (= 従来の挙動へ戻る。安全網が黙って消えることはない)。
    """
    try:
        def _hd(m):
            head = cmd[:m.start()].rsplit("\n", 1)[-1]
            head = head.split("|")[-1].split("&")[-1].split(";")[-1]
            if _SHELL_SINK.search(head.strip()):
                return m.group(0)      # ★シェルに食わせる=実行される。潰さない
            return " " * len(m.group(0))
        out = _HEREDOC.sub(_hd, cmd)
        return _QUOTED.sub(_blank, out)
    except Exception:
        return cmd


def verdict(cmd):
    """止めるべきなら理由を返す。通してよいなら None。"""
    target = mask_inert(cmd)
    for pat, how in _RULES:
        if re.search(pat, target):
            return pat, how
    return None


def main():
    try:
        ev = json.load(sys.stdin)
    except Exception:
        return 0                       # ★入力が読めない=判定不能。通す(fail-open)
    try:
        if ev.get("tool_name") != "Bash":
            return 0
        cmd = str((ev.get("tool_input") or {}).get("command") or "")
        if not cmd:
            return 0
        hit = verdict(cmd)
        if not hit:
            return 0
        _, how = hit
        sys.stderr.write(
            "【機構で停止】このコマンドは作業ツリーを壊す形だ。\n"
            "  コマンド: %s\n"
            "  なぜ止めた: %s\n"
            "  ★これは .claude/settings.json の PreToolUse フック"
            "(scripts/hooks/guard_destructive.py)による停止で、allowルールより強い。\n"
            "  ★どうしても必要なら、実行せずChamiへ上げろ(不可逆はChamiの領域)。\n" % (cmd, how))
        return 2
    except Exception:
        return 0                       # ★フックのバグで全部屋を止めない


if __name__ == "__main__":
    raise SystemExit(main())
