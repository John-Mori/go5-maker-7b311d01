---
name: daemon-reload-check
description: 常駐(デーモン)が読むファイルを足した・直した時に、載せ替えの経路まで決めるための手順。scripts/_daemons/ や scripts/llm/ の常駐が import するモジュール、部門の名簿、共通規律、characterfile 等を触った後に使う。「直したのに動かない」「常駐が古い版で走っている」を防ぐ。裁定C-042の執行手順。
---

# 常駐の載せ替え(C-042)

## なぜ要るのか
**ファイルを直しても、常駐は古い版で走り続ける。** これが「直したのに直っていない」の最頻出の形で、
改修ログ736行のうち **43件**がこの型だった。裁定C-042(2026-08-12)はこの「また忘れた」から生まれている。

★**あなたが直した瞬間に効くのは、あなたのセッションだけだ。** 30体の dept_daemon は別プロセスで走っている。

## 触った直後に必ず答える3問

1. **それは `daemon_keeper.WATCH_FILES` に載っているか?**
   現在の9本(`scripts/_daemons/daemon_keeper.py`):
   `dept_daemon.py` / `scripts/llm/session_relay.py` / `scripts/llm/session_rooms.py` /
   `scripts/llm/tone_gate.py` / `scripts/llm/naming_gate.py` / `scripts/queue/leasequeue.py` /
   `scripts/_common/session_presence.py` / `scripts/discord/persona_send.py` / `scripts/_common/dept_names.py`
   → **常駐が import するのに載っていないなら、載せる。** 検査= `python scripts/_daemons/test_daemon_keeper.py`
   (`unwatched_imports()` が import と WATCH_FILES を突き合わせて数える。空でなければ載せ忘れ)。

2. **都度読みか、起動時に1回読むだけか?**
   共通規律・org_registry・characterfile のように `dept_daemon` が**都度読み**するものは、
   **編集した瞬間から次の便に効く**=載せ替え不要。★「配る」必要はない。編集して終わり。
   起動時に1回しか読まないものは、載せ替えないと永久に効かない。**どちらかを必ず確かめる。**

3. **keeper 自身を直したか?**
   `daemon_keeper.py` は **自分自身を監視していない**。直しても1回落とすまで古い版で走る。
   → `python scripts/_daemons/reload_keeper.py --detach`(暇な窓を待って落とし、すぐ立て直す)。
   ★★**自室のセッションから前景で走らせるな。永久に待つ。**「暇な窓」は全部門が便を握っていない
   瞬間だが、**自室は自分のターンが終わるまで inflight** なので待っている側が待たれている側になる
   (2026-08-13に08:20と08:58の2回、`待機中(処理中=aegis-gl)` で止まった実測)。必ず `--detach`。

## 載せ替えの副作用(知って選ぶ)
- 新しい keeper は孤児を掃除して**全部門を立て直す**=その時点の `dept_daemon.py` が全30体に載る。
- 便は消えない。LeaseQueue は ack されなければ lease 満了で再配達する(deliveries が1増えるだけ)。
- 連続改修中は間引きが効く(`RELOAD_DEBOUNCE_SEC=90` / `RELOAD_MIN_INTERVAL_SEC=600`)。
  2026-07-29に**全28体が数分おきに再起動し続け、載せ替えが便の処理を食い潰した**のがこの下限が無かった時。

## 「効いた」の確かめ方
- 常駐のpidが変わったことと、**便が1本通ったこと**の両方を見る。pidだけでは足りない。
- ★**新しい版が載ったかは、新しく処理された便の実物で見る**(C-041= 一度の観測を状態の代理にするな)。
- ここまでで言えるのは「効いた」まで。**症状が出ていたのと同じ場面**で見るまで「直った」と書かない(§4.55)。
