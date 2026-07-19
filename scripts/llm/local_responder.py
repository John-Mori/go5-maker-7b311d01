#!/usr/bin/env python3
"""ローカルLLM受付係 (Discord一次応答・Claudeセッション不在時の24時間窓口)。

仕組み(2026-07-15 変更・Chami指示「一次受けにローカルを挟むな・全部門で排除」):
  - **部門の依頼(main箱 discord_inbox.jsonl)には一切触れない**。以前はClaude不在時にmain箱を
    ドレインしてqwen応答/for_claude箱へ再エスカレしていたが、それが「依頼が横取りされて司令塔に
    届かない/無視される」原因だった。部門の依頼は司令塔(Claude)専任=main箱のまま待たせる。
  - ローカルqwenが応対するのは**自室 llm-growth(discord_inbox_llm.jsonl)だけ**。
  - 質問系: Ollama(知識パック注入)で即答 → persona_send「ローカルqwen」名義で返信
  - 処理済みは local/discord_inbox_processed.jsonl へ移動。応答ログは local/llm/responder_log.jsonl
使い方: python scripts/llm/local_responder.py [--once]
常駐: scripts/llm/start_local_responder.bat
"""
import json
import os
import subprocess
import sys
import time

try:
    # line_buffering=True が必須(INC-93): 常駐はログをファイルへリダイレクトして走るが、
    # ファイル向けstdoutは約8KBのブロックバッファになる。無口な常駐は8KBに到達せず、
    # 再起動時のStop-Process -Forceで未書き出し分が破棄される=ログが1行も残らない。
    # (鳩は7/14から3日間、6バイトのまま凍結していた。壊れた時に追う道具が壊れていた)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from ask_local import ask  # noqa: E402
from ask_vision import describe_images  # noqa: E402
from image_prep import images_of  # noqa: E402

LOCAL = os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_inbox_processed.jsonl")
# ★L0(2026-07-18 Chami「残っていることをよろしく」で実装): エスカレ先=main箱へ変更。
#   旧 for_claude箱は「消費者=セッション開始時の研究室だけ」で、長寿命セッションでは誰も読まず
#   Chami直令が1.2h滞留する実害が出た(QA発見)。main箱ならwaiterのチャイムが鳴る=無音滞留が
#   構造的に消える。裁定の原典=memory: escalation-to-main-box(2026-07-17)。旧箱は完全退役。
FOR_CLAUDE = os.path.join(LOCAL, "discord_inbox.jsonl")  # エスカレ先=main箱(変数名は互換のため維持)
CLAUDE_ACTIVE = os.path.join(LOCAL, "llm", "claude_active.txt")
LOG = os.path.join(LOCAL, "llm", "responder_log.jsonl")
PERSONA = "ローカルqwen"  # 旧名「ローカル受付」(Chami改名2026-07-13)
MODEL = "qwen3:8b"  # RTX 3060 Ti 8GBで実測55秒/回・品質向上のため4b→8bへ格上げ(2026-07-13)
INBOX_LLM = os.path.join(LOCAL, "discord_inbox_llm.jsonl")  # llm-growth部屋専用=Claude稼働中でも本人が応対
QDB = os.path.join(LOCAL, "queue", "inbox.db")  # ★O1(2026-07-20): カットオーバー後の受信経路
QUEUE_DEPT = "llm-growth"  # 自室のdept(discord_channels.json)
WORK_WORDS = ("直して", "修正", "実装", "追加して", "デプロイ", "変えて", "作って", "調べて", "特定して",
              "バグ", "エラー", "壊れ", "対応して", "やって", "反映", "消して", "削除")


def claude_is_active():
    # 判定は共有ヘルパへ一本化(2026-07-18 INC対策): 旧・claude_active.txt 90秒単独ゲートは
    # 「mainが作業中で耳(waiter脈)が一時途切れただけ」でも不在と誤判定し、generic即答を暴発させた。
    # presence.lab_alive は readiness(耳) OR liveness(toolフック脈)+HARD_CAP の2信号で判定する。
    from presence import lab_alive  # sys.path に HERE を追加済(冒頭)
    return lab_alive()


def send(channel, text):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
                        "--channel", channel, "--persona", PERSONA, text],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_line(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


AUDIO_EXT = (".ogg", ".m4a", ".mp3", ".wav", ".webm")


def fetch_and_transcribe(url):
    """Discordの音声添付をダウンロードして文字起こし(失敗時は空文字)。"""
    import urllib.request
    tmp = os.path.join(ROOT, "local", "llm", "voice_tmp.bin")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (go5-responder)"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        from transcribe import transcribe
        return transcribe(tmp)
    except Exception as e:
        print(f"  文字起こし失敗: {type(e).__name__}")
        return ""


SENSITIVE_DEPTS = ("dream-care", "past-room", "future-room", "hr-room", "health-log")  # 夢と回復/過去の共有/現在と未来(2026-07-17新設)/人事/健康記録=研究室直轄・機微。ローカルLLMは応答せず受領印のみ
# ★画像をローカルVLMに渡してよい部門(allow-list=fail-closed)。ここに無い部門・dept未設定の
#   行の画像は一切VLMに渡さない。deny-listだと部屋の新設時に追記を忘れた瞬間に機微画像が
#   VLMへ流れる(実際SENSITIVE_DEPTSは4箇所に散在しドリフトしている)。迷ったら見ない、が正。
VISION_ALLOWED_DEPTS = ("llm-growth",)


def handle(rec, raw_line):
    content = rec.get("content", "")
    channel = rec.get("channel", "")
    if rec.get("dept") in SENSITIVE_DEPTS:
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "受け取ったよ。ここは司令塔(アメスたち)が直接読む部屋だから、次に起きた時に必ず応えるね。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "sensitive_deferred", "channel": channel})
        return
    # ★V0シャドー配線(改善設計書_ローカルLLM画像認識強化_2026-07-17 §3・T-2)
    #   画像添付は司令塔(Claude)へ回し、ローカルVLMの**下読み(vision_draft)を箱の行に添える**。
    #   狙いは (a)司令塔が画像を開く前に中身の当たりが付く (b)qwenの画像読解の質が
    #   ログに溜まり週次で採点・測定できる(=llm-growthの見える化の材料になる)。
    #   ※正直な但し書き: 「画像+テキスト」はV0以前はqwenが(画像を見ずに)即答していたため、
    #     V0で即答→エスカレへ**判断が変わる**通がある。即答率/エスカレ率の傾向が画像の混入で
    #     動くので、週報では vision:true を分けて読む必要がある(指標定義は変えない=R3)。
    #   VLMが落ちても配達は止めない: describe_imagesは例外を投げない設計だが、契約に依存せず
    #   ここでもtryで包む(2026-07-17レビュー: importが契約を貫通し得た実例があったため)。
    #   ★機微はallow-list方式(fail-closed)。deny-list(SENSITIVE_DEPTS)は部屋が増えるたびに
    #     追記漏れが起き、dept未設定の行も素通りする。VLMに渡してよい部屋だけを明示列挙する。
    imgs = images_of(rec) if rec.get("dept") in VISION_ALLOWED_DEPTS else []
    if imgs:
        try:
            v = describe_images(imgs)
        except Exception as e:
            v = {"draft": "", "model": "", "sec": 0.0, "error": f"vision_crashed:{type(e).__name__}"}
        rec = dict(rec, vision_draft=v["draft"], vision_model=v["model"], vision_sec=v["sec"])
        raw_line = json.dumps(rec, ensure_ascii=False)
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "画像を受け取ったよ。読み取りメモを添えて司令塔の受付箱に入れておくね。")
        # mode は既存の "escalated" のまま(=司令塔へ回した、の意味は同じ)。
        # 画像かどうかは vision フィールドで見分ける。modeを増やすと learning_report.py の
        # 即答率/エスカレ率の分母分子がずれるため(指標は再定義しない=改善設計書R3)。
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "q": (content or "(画像のみ)")[:200], "vision": True, "vision_model": v["model"],
             "vision_sec": v["sec"], "vision_draft": v["draft"][:300], "vision_error": v["error"]})
        print(f"  画像→Claude行き(下読み{len(v['draft'])}字/{v['sec']}秒) [{channel}]")
        return
    if not content.strip():
        voice = next((a for a in (rec.get("attachments") or [])
                      if any(x in a.lower() for x in AUDIO_EXT)), "")
        if voice:
            content = fetch_and_transcribe(voice)
            if not content:
                append_line(FOR_CLAUDE, raw_line)
                append_line(PROCESSED, raw_line)
                send(channel, "ボイスメモを受け取ったけど聞き起こせなかったから、司令塔の受付箱に入れておくね。")
                log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated_voice_fail", "channel": channel})
                return
            rec = dict(rec, content=content, voice=True)
            raw_line = json.dumps(rec, ensure_ascii=False)
    is_work = any(w in content for w in WORK_WORDS)
    answer = ""
    if not is_work:
        try:
            answer = ask(content, MODEL)
        except Exception as e:
            print(f"  LLM失敗: {type(e).__name__} → Claude行き")
            answer = ""
        if answer and ("わからないので司令塔" in answer or "ESCALATE" in answer):
            answer = ""
    if answer:
        ok = send(channel, answer)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered", "channel": channel,
             "q": content[:200], "a": answer[:300], "sent": ok})
        append_line(PROCESSED, raw_line)
        print(f"  即答 [{channel}] {content[:30]!r}")
    else:
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "これは司令塔(Claude)の仕事として受付箱に入れておくね。次のセッションで対応されるよ。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "q": content[:200]})
        print(f"  Claude行き [{channel}] {content[:30]!r}")


def drain_lines(path):
    """受付箱を .inflight へ退避して全行を返す(既に退避済みがあればそれを優先)。

    ★kill耐性(2026-07-17): 旧実装は「読む→os.remove→処理」で、処理中に強制終了
      (Windows Update再起動・stop_daemons・重複排除のkill)が入ると、箱から消えて
      まだ着地していない行が**どこにも残らず消滅**した(レビューで3通中2通の喪失を再現)。
      inflightに残しておけば、次回起動時に拾い直せる=喪失が「遅延」に変わる。
    """
    inflight = path + ".inflight"
    if os.path.exists(inflight) and os.path.getsize(inflight) > 0:   # 前回の中断分が最優先
        with open(inflight, "r", encoding="utf-8") as f:
            rest = [l for l in f.read().splitlines() if l.strip()]
        if os.path.exists(path) and os.path.getsize(path) > 0:       # 新着があれば後ろに繋ぐ
            with open(path, "r", encoding="utf-8") as f:
                rest += [l for l in f.read().splitlines() if l.strip()]
            os.remove(path)
        _write_inflight(inflight, rest)
        return rest, inflight
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return [], inflight
    with open(path, "r", encoding="utf-8") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    os.replace(path, inflight)     # 原子的に退避(この瞬間に落ちてもinflightに全行が残る)
    return lines, inflight


def _write_inflight(path, lines):
    if not lines:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)          # 書き換えも原子的に(途中で落ちても壊れた箱を残さない)


def _processed_msg_ids():
    ids = set()
    try:
        for pl in open(PROCESSED, encoding="utf-8", errors="replace"):
            try:
                m = json.loads(pl).get("msg_id")
                if m:
                    ids.add(str(m))
            except Exception:
                continue
    except OSError:
        pass
    return ids


def drain_queue():
    """★O1(改善書P0-1): llm-growth宛はカットオーバー(2026-07-19 鳩退役)後、
    jsonl(discord_inbox_llm.jsonl)には来ず LeaseQueue に入る。旧実装はjsonlしか
    見ていなかったため llm-growth が事実上無応答だった(30分放置エスカレまで沈黙)。
    ここで queue の dept='llm-growth' を claim→handle→ack する。二重処理はPROCESSED台帳で防ぐ。
    dept_daemon.drain_queue と同じ契約。DBが無い間は何もしない(fail-open)。"""
    if not os.path.exists(QDB):
        return 0
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QDB)
    except Exception:
        return 0
    done = 0
    try:
        processed = _processed_msg_ids()
        while done < 5:  # 1巡回の上限(暴走ガード)
            c = q.claim(dept=QUEUE_DEPT, who="local_responder")
            if c is None:
                break
            rec = c["body"] if isinstance(c["body"], dict) else {}
            mid = str(rec.get("msg_id", c.get("msg_id") or ""))
            if mid and mid in processed:
                q.ack(c["id"], result="skip(処理済)")
                continue
            try:
                handle(rec, json.dumps(rec, ensure_ascii=False))
                q.ack(c["id"], result="qwen応答")
            except Exception as e:
                # 失敗は握りつぶさずmain箱へ回す(dept_daemonと同じ安全網)
                q.ack(c["id"], result=f"失敗:{type(e).__name__}")
                append_line(FOR_CLAUDE, json.dumps(rec, ensure_ascii=False))
            done += 1
    finally:
        q.close()
    if done:
        print(f"  queue経路 {done}件処理 [llm-growth]")
    return done


def main():
    once = "--once" in sys.argv
    print(f"ローカル受付 起動 (model={MODEL}, 30秒間隔, Claude稼働中は待機)")
    while True:
        # llm-growth部屋(自分の部屋)はClaude稼働中でも常時応対
        llm_lines, inflight = drain_lines(INBOX_LLM)
        if llm_lines:
            for i, line in enumerate(llm_lines):
                try:
                    handle(json.loads(line), line)
                except Exception as e:
                    print(f"  処理失敗(llm箱): {type(e).__name__}")
                    append_line(FOR_CLAUDE, line)
                # 1行を着地させるたびに残りだけをinflightへ書き戻す。
                # 落ちても「未処理の行だけ」が残る(着地済みの重複返信より、喪失を避ける方を採る)。
                _write_inflight(inflight, llm_lines[i + 1:])
        # ★O1: カットオーバー後の本経路=LeaseQueue(dept='llm-growth')をドレイン。
        #   上のjsonl(discord_inbox_llm.jsonl)は鳩退役で新着が来ないため、こちらが実体。
        try:
            drain_queue()
        except Exception as e:
            print(f"  queue drain失敗: {type(e).__name__}")
        # ★main箱(部門の依頼)には一切触れない=ローカルを一次受付として挟まない
        #   (Chami指示2026-07-15「一次受けにローカルを挟むな・全部門で排除」)。
        #   以前はClaude不在時にmain箱をドレインしてqwen応答/for_claude箱へ再エスカレしていたが、
        #   それが「依頼が横取りされて司令塔に届かない/無視される」原因だった。
        #   部門の依頼は司令塔(Claude)の専任。main箱はそのまま司令塔が処理する。
        #   ローカルqwenは自室 llm-growth(上の INBOX_LLM)だけを応対する。
        if once:
            print("1回分の処理完了(自室llm-growthのみ・main箱は司令塔専任)")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
