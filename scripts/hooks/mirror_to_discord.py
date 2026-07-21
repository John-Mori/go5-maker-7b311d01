#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stop hook: このClaude Codeセッションのやり取りを、対になるDiscord部屋へミラーする。

Chami最優先事項(2026-07-20):「ここでのやり取りをDiscordとメッセージで同期させること」。
**一部屋=一セッションで対になっているところだけ**を対象にする(部屋の無いセッションは保留)。

なぜhookなのか:
  私(Claude)の心がけに任せると忘れる。実際この日、20部屋へ告信して「周知した」と報告したが
  gatewayがwebhookを弾いており誰にも届いていなかった。Anthropic公式も
  「CLAUDE.mdの指示はお願いであって保証ではない。hookが強制」と明言している。
  → 同期は**ハーネスが実行するhook**で担保する。

設計:
  - Stop hookのstdin JSONから transcript_path を取る
  - 前回ミラー済みのuuid以降の「本文だけ」を拾う(tool_use/tool_resultは送らない)
  - Chamiの発言 = "Chami(from Claude)" 名義(persona_sendがサイレント扱い=通知を鳴らさない)
    私の応答     = "シャビ・アロンソ" 名義(HQ部屋の研究室の声。アメスは常駐デーモンの声なので分ける)
  - **初回(状態ファイル無し)は直近1往復だけ**送る(全履歴をDiscordへ流し込まない)
  - ループしない: 送信はwebhook -> gatewayがbot/webhookを弾く -> 戻ってこない
  - **絶対にセッションを止めない**: 例外は握り潰し、常にexit 0。decisionも返さない
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
STATE = os.path.join(LOCAL, "mirror_to_discord_state.json")

# 一部屋=一セッションの対応。正本は scripts/llm/session_rooms.py に1箇所だけ置く
# (ミラー先と在席記録が別々に表を持つと、片方だけ増やした時に二重応答が静かに復活する)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
from session_rooms import dept_of_payload, touch_presence  # noqa: E402
import persona_render  # noqa: E402
CHAMI_NAME = "Chami(from Claude)"   # persona_send側で通知を鳴らさない名義(mirror判定)
# ★2026-07-21 Chami「話が長すぎてDiscord上だと途切れてます。前も言おうとしたけど」
#   真因= **ここで切っていた**。persona_send は split_body() で1900字ずつ正しく分割して
#   全文を送る実装になっている(6452字が切れた事故の対処済み)のに、その手前で本文を
#   3500字に詰めて捨てていた。=**下流の恒久対処を上流が無効化していた**。
#   → 上限を上げて分割に任せる。暴走(数万字)だけは止める。
#   ★ただし本当の対処は**書く側が短く書くこと**。機構は取りこぼしを防ぐだけで、
#     長文が4通に分かれて届く読みにくさは解決しない。
MAX_CHARS = 9000                    # ≒Discord 5通ぶん。これを超える時だけ末尾を落として注記

# ★Discordへ流すだけでは**デーモンには何も伝わらない**(2026-07-20実測):
#   gatewayがwebhook投稿を弾く -> キューに入らない -> dept_daemonのmemory_appendが走らない
#   -> 常駐キャラ(アメス)は研究室が何をしたか一切知らないまま、同じ質問をChamiに繰り返す。
#   なので記憶ストアへ**直接**追記する。これでデーモンが引き継ぐ時に文脈を持てる。
HQ = os.path.join(os.path.dirname(ROOT), "00_AI-HQ")
MEM_DIR = os.path.join(HQ, "departments", "hr", "memory")
MEM_OF = {"hq": os.path.join(MEM_DIR, "hq.jsonl")}


def memory_append(dept, who, body):
    """デーモンの記憶ストアへ直接追記する(キューを経由しないため)。"""
    p = MEM_OF.get(dept)
    if not p:
        return
    try:
        import time
        os.makedirs(os.path.dirname(p), exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "msg_id": "",
                 "from": who, "content": body[:500], "reply": "",
                 "src": "claude-code-session"}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:
        pass


MIRROR_IDS = os.path.join(LOCAL, "llm", "mirror_msgids.jsonl")


def record_mirror_id(dept, channel_hint, stdout):
    """ミラーで投稿した `Chami(from Claude)` のmsg_idを控える。

    ★2026-07-18 Chami指示(orchestration.md §139)= 「貼った本人のセッションは、表示された
      msg=IDへ既読印を即押し、作業開始時に着手印を押す」。**ミラーにも4状態の可視化を通す**。
      2026-07-21 Chami「Chami(from Claude)にも既読と着手をつけて欲しいってことも
      忘れられてるから再びよろしく」= **指示は2度目**。今度は機構に載せる。
    persona_sendが `msg=<id>` を標準出力に出すので、それを拾って進捗印の対象に加える。
    """
    try:
        ids = re.findall(r"msg=(\d+)", stdout or "")
        if not ids:
            return
        os.makedirs(os.path.dirname(MIRROR_IDS), exist_ok=True)
        with open(MIRROR_IDS, "a", encoding="utf-8") as f:
            for mid in ids:
                f.write(json.dumps({"dept": dept, "msg_id": mid,
                                    "channel": channel_hint}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def body_key(who, body):
    """送信済み判定のキー。uuidではなく**中身**で見る。"""
    import hashlib
    return hashlib.sha1((who + "\x00" + body).encode("utf-8", "replace")).hexdigest()[:16]


SENT_KEEP = 120                     # セッションあたり保持する送信済みキー数(古い順に捨てる)

# ★ハーネスが差し込む行はChamiの発言ではないので流さない(2026-07-21 Chami指示
#   「画像やファイルを添付して送った場合はそのファイル名とかは書かなくていい。無駄」)。
#   添付を送った時に出る2種類=アップロード先の絶対パスと、画像寸法の注記。
NOISE_PREFIXES = ("[Image:", "[Screenshot", "[File:")


# 添付パスの表記。★行頭だけでなく**本文と同じ行に続く**ケースがある
#   (実測: `@"C:\...\uploads\...IMG_1336.png" 大体こういうメール、6通来てた。`)
#   ので、行まるごと落とすのではなく**その部分だけ**除去する。
ATTACH_PATH_RE = re.compile(r'@?"[A-Za-z]:[\\/][^"\n]*[\\/]uploads[\\/][^"\n]*"|@?[A-Za-z]:[\\/]\S*[\\/]uploads[\\/]\S+')


def strip_attachment_noise(body):
    """添付由来のメタ(パス・寸法注記)を落とす。全部メタなら空を返す=送らない。"""
    keep = []
    for ln in body.splitlines():
        if ln.strip().startswith(NOISE_PREFIXES):
            continue                # 寸法注記の行はまるごと捨てる
        ln = ATTACH_PATH_RE.sub("", ln).strip()
        if ln:
            keep.append(ln)
    return "\n".join(keep).strip()


def text_of(entry):
    """本文テキストだけを取り出す。tool_use/tool_resultやメタは対象外。"""
    msg = entry.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    out = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            t = (b.get("text") or "").strip()
            if t:
                out.append(t)
    return "\n\n".join(out).strip()


def send(dept, persona, body):
    if not body:
        return
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + "\n\n…(長いのでここまで。全文はClaude Code側にあります)"
    if os.environ.get("MIRROR_DRY"):   # 検証用: 送らず何を送るかだけ出す
        print(f"[DRY] dept={dept} persona={persona} chars={len(body)}\n  {body[:160]}...")
        return
    try:
        p = subprocess.run(
            [sys.executable, PERSONA_SEND, "--dept", dept, "--persona", persona, body],
            capture_output=True, timeout=60, text=True, encoding="utf-8", errors="replace")
        if persona == CHAMI_NAME:
            record_mirror_id(dept, dept, p.stdout or "")
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    # 念のためのループ保険。Stop hookが再入した時は何もしない
    if payload.get("stop_hook_active"):
        return
    dept, my_name = dept_of_payload(payload)
    if not dept:
        return                      # 対になる部屋が無いセッションは保留(Chami指示)
    # ターン終了時点でも在席を延長する。PostToolUseが一度も鳴らないターン(道具を使わず
    # 会話だけで返したターン)では在席が枯れており、直後の便をデーモンが攫うため。
    touch_presence(dept)
    # ★進捗印はここでは押さない。既読/着手/即答は**時系列を表す信号**なので、
    #   ターン終了時にまとめて押すと時系列が消える(初版の誤り)。
    #   正しい担当= scripts/hooks/progress_mark.py(UserPromptSubmit=既読 /
    #   PostToolUse=着手 / Stop=即答)。仕様の正本= 運用細則_セッションと起床.md §37。
    tp = payload.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return

    entries = []
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return

    sid = payload.get("session_id") or "default"
    st = load_state()
    last_uuid = (st.get(sid) or {}).get("last_uuid")
    # ★送信済みキー(2026-07-21 Chami実測「全く同じ返答がDiscordに2回ずつ送られた」への恒久対処)。
    #   真因= 再開位置を **uuid** だけで決めていたこと。保存した last_uuid が transcript から
    #   引けないと `start=None` → 「初回」扱いに落ちて**直近の1往復を再送する**。
    #   引けなくなる経路は複数ある(uuidを持たない行でnewestが進まない/履歴の作り直し/
    #   同一ターン内の再発火)ので、**位置の推定に頼るのをやめて中身で照合する**。
    sent = list((st.get(sid) or {}).get("sent") or [])
    sent_set = set(sent)

    start = None
    if last_uuid:
        for i, e in enumerate(entries):
            if e.get("uuid") == last_uuid:
                start = i + 1
                break
    if start is None:
        # 初回 or 履歴が作り直された: 直近の1往復だけに絞る(全履歴を流さない)。
        # ★末尾はtool_use/tool_resultが並ぶので「本文を持つ行」だけを数える
        #   (単に最後の2件を取ると本文ゼロで何も送らない=2026-07-20の実測で判明)
        idxs = [i for i, e in enumerate(entries)
                if e.get("type") in ("user", "assistant") and text_of(e)]
        start = idxs[-2] if len(idxs) >= 2 else (idxs[-1] if idxs else len(entries))

    # ★1ターン=1発言にまとめる(2026-07-20 Chami指摘「人格が消えてる」への対処):
    #   従来は私の応答を段落ごとに個別送信していたため、素のmarkdownの断片が10連投され、
    #   部屋が読めなくなっていた(実測で56件が一度に流れた)。私の発言はバッファに溜め、
    #   最後にpersona_renderで1つの発言へ束ねる。記憶ストアへは従来どおり1件ずつ残す
    #   (アメスの文脈は細かい方が効くので、Discordの見た目とは別扱いにする)。
    newest = None
    mine = []

    def flush_mine():
        """溜めた自分の発言のうち**最後の1つ(=結論)だけ**を送る。既送なら送らない。

        ★2026-07-21 Chami指摘(ORG-23):
          「この謎の英文はディスコードには要らない、無駄、読みにくい。逆にあることで(邪魔)。
           アイアムジャパニーズ」
          道具を叩く前に書く短い実況(「〜を確認する」「Let me check X」)まで全部Discordへ
          流していたため、部屋が実況で埋まって**結論が読めなくなっていた**。
          しかも実況は英語で書かれることがあり、日本語話者の部屋に英文が混ざっていた。

        ★なぜ「最後の1つ」で正しいか: 1ターンの中で、道具の前に置く文は**予告**であって
          結論ではない(=Discordの読者に価値が無い)。最後のテキストがそのターンの報告。
          元の実装は全部を連結していたが、docstring冒頭の設計意図
          「★1ターン=1発言にまとめる」に照らしても、**連結ではなく結論1本**が正しい。
          途中経過はClaude Code側に全部残っているので情報は失われない。
        """
        if not mine:
            return
        joined = mine[-1].strip()      # ★予告(道具前の実況)は捨て、結論だけを届ける
        k = body_key(my_name, joined)
        del mine[:]
        if k in sent_set:
            return
        sent_set.add(k)
        sent.append(k)
        send(dept, my_name, persona_render.render(dept, [joined], persona=my_name))

    for e in entries[start:]:
        t = e.get("type")
        # ★newestは種別に関わらず進める。user/assistant限定にしていたため、末尾が別種別だと
        #   状態が古いuuidのまま残り、次の発火で再送の起点になっていた。
        newest = e.get("uuid") or newest
        if t not in ("user", "assistant"):
            continue
        body = text_of(e)
        if not body:
            continue                # tool_result等は送らない
        if t == "user":
            if body.startswith("<") or "system-reminder" in body[:200]:
                continue            # ハーネス注入は人の発言ではない
            if body.startswith("[SYSTEM NOTIFICATION"):
                continue            # 背景タスクの通知もChamiの発言ではない
            body = strip_attachment_noise(body)
            if not body:
                continue            # 添付のパス・寸法だけの行は流さない(Chami指示)
            flush_mine()            # Chamiの発言より前に、溜まっていた自分の分を先に出す
            k = body_key(CHAMI_NAME, body)
            if k in sent_set:
                continue
            sent_set.add(k)
            sent.append(k)
            send(dept, CHAMI_NAME, body)
            memory_append(dept, "chami", body)
        else:
            mine.append(body)
            memory_append(dept, my_name, body)
    flush_mine()

    st[sid] = {"last_uuid": newest or last_uuid, "sent": sent[-SENT_KEEP:]}
    save_state(st)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)                     # 何があってもセッションを止めない
