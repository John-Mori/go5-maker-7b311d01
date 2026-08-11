#!/usr/bin/env python3
"""出力ゲート ルールD(口調ドリフト検知)=純関数(LLM不要・テスト可・警告のみ)  2026-08-03.

設計書= 00_AI-HQ/設計_口調ゲート_送信直前_名乗りと本文の食い違い_2026-08-03.md。
裁定= 研究室HQ(msg 1533789472783863899)「①警告のみ段階=投入Go / ②LLM審級はinlineにしない」。

判定は (話者=persona名, 部屋=dept, 本文) の三つ組。呼称ゲート(ルールC=naming_gate)と
**同じ送信直前地点**(dept_daemon.audit_naming と同じブロック)へ相乗りする兄弟チェック。

一次(このモジュール)=純関数で「名乗り[名前]と本文の一人称の露骨な食い違い」だけを拾う。
  例: アメス(一人称=あたし)のブロックに「オレ」= 別人格ククール/デブライネの一人称=食い違い。
意味的ドリフト(一人称も語尾も踏まずに距離感だけ別人格へ寄る=DEF-hq-6999e18608「アロンソ口調」型)は
  純関数では拾えない=**このゲートの対象外**(HQ裁定②=inline LLMは却下・二次で別途)。

★fail-open(HQ裁定①で厳守指示): 例外・ルール未ロードは**空リスト**を返す=ゲート自身が配送を殺さない。
★このゲートは**本文を一切変えない**(警告のみ=naming_corrections のような自動修正は持たない)。
★ORG-11(判定を2本持たない): 口調判定はこの1本に集約する。写像1本=口調ルール.json。
"""
import json
import re

# 判定に使う「distinctive(識別力のある)一人称」だけを対象にする。
#   私 / わたし / うち / 自分 は中立・多義(私立・私的…)で誤検知が高いので**対象外**
#   (警告のみMVP=まず誤検知率を低く保って実測する。HQ裁定①「誤検知率を実測できる形」)。
DISTINCTIVE_MARKERS = (
    "オレ", "俺", "僕", "ぼく", "あたし", "あたい",
    "わし", "わっち", "拙者", "小生", "あちき",
)

_KATAKANA = re.compile(r"[ァ-ヴ]")
# 「…」『…』で囲まれた span=他人格のセリフ引用でありうる=一人称判定から外す(FP抑制)。
_QUOTE_SPAN = re.compile(r"「[^「」]*」|『[^『』]*』")


def load_tone_rules(path):
    """口調ルール.json を読み込む。読めなければ None(呼び出し側で fail-open)。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _norm(s):
    """人格名の表記ゆれ(中黒・空白)を吸収して突き合わせる(naming_gate と同じ思想)。"""
    return re.sub(r"[・\s]", "", str(s or "")).lower()


def _strip_quotes(s):
    """引用span を長さ保存で潰す(位置がズレないよう全角空白へ置換)。

    他人格のセリフ引用(例: デブライネが『アメスは「あたし」と言った』)で
    一人称ゲートが誤爆するのを防ぐ=最頻の false-positive を1つ消す。
    """
    return _QUOTE_SPAN.sub(lambda m: "　" * len(m.group(0)), str(s or ""))


def _persona_entry(rules, persona):
    """人格エントリを中黒無視で引く。無ければ None(=判定対象外=スキップ)。"""
    personas = (rules or {}).get("personas") or {}
    if persona in personas:
        return personas[persona]
    n = _norm(persona)
    for k, v in personas.items():
        if _norm(k) == n:
            return v
    return None


def _registry_distinctive(rules):
    """レジストリ全体に現れる distinctive 一人称の集合(=誰かの正規一人称であるものだけ)。"""
    personas = (rules or {}).get("personas") or {}
    seen = set()
    for v in personas.values():
        for fp in (v.get("first_person") or []):
            if str(fp) in DISTINCTIVE_MARKERS:
                seen.add(str(fp))
    return seen


def _scan_marker(s, marker):
    """s 中の marker の最初の「有効な」出現位置。無ければ -1。

    ★カタカナ marker(オレ 等)は、直後もカタカナなら別語(オレ→オレンジ)としてスキップ。
      漢字/ひらがな marker(俺・僕・あたし)はこのガードを掛けない。
    """
    is_kata = bool(_KATAKANA.search(marker))
    start = 0
    while True:
        i = s.find(marker, start)
        if i < 0:
            return -1
        after = s[i + len(marker):i + len(marker) + 1]
        if is_kata and after and _KATAKANA.match(after):
            start = i + len(marker)   # オレンジ等=別語=この出現は無効
            continue
        return i


def tone_verdicts(persona, dept, text, rules):
    """口調違反(=一人称の食い違い)の候補一覧を返す(純関数・警告のみ)。

    引数:
      persona : 話者(解決済みの正式名。split_persona_blocks の resolve 結果 or 既定名)。
      dept    : 部屋(監査記録用。判定には現状未使用)。
      text    : ブロック本文。
      rules   : load_tone_rules() の戻り(dict) or None。

    返り値: list[dict]。各要素=
      {"persona","marker","index","own_first_person":[...],"reason":"first_person_mismatch"}
    違反が無ければ空リスト。ルール未ロード/例外/未登録人格は空リスト(fail-open)。
    """
    out = []
    try:
        if not rules:
            return out
        ent = _persona_entry(rules, persona)
        if not ent:
            return out            # 未登録の人格は判定しない(fail-open=鳴らさない)
        own = {str(x) for x in (ent.get("first_person") or [])}
        # 禁止= レジストリ上の distinctive 一人称のうち、自分のものでないもの。
        #   (レジストリに人格を足せば自動で他人格の一人称が禁止対象になる=正本1本)。
        forbid = sorted(_registry_distinctive(rules) - own)
        if not forbid:
            return out
        s = _strip_quotes(text)
        if not s.strip():
            return out
        for m in forbid:
            i = _scan_marker(s, m)
            if i >= 0:
                out.append({
                    "persona": str(persona or ""),
                    "marker": m,
                    "index": i,
                    "own_first_person": sorted(own),
                    "reason": "first_person_mismatch",
                })
        return out
    except Exception:
        return []                 # fail-open=ゲートは配送を殺さない
