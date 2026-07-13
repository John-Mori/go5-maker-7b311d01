#!/usr/bin/env python3
"""AIオフィス DF-1: D1の実データから部屋型バーチャルオフィスHTMLを生成する。

設計: docs/設計・調査/AIオフィス_部屋型_設計書_v1.md
原則: 偽Status禁止——吹き出し・状態は全て dept_tasks / dept_events / system_changes の実データ由来。
      タスクが無い部門は正直に「待機」(persona定義の待機演出はツールチップで「演出」と明示)。
出力: local/office/index.html (自己完結・外部依存ゼロ・非公開=ローカル専用)
使い方: python scripts/office/build_office.py [--open]
"""
import datetime
import html
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "local", "office", "index.html")

ROSTER = [
    {"dept": "司令塔", "label": "司令塔・研究室", "color": "#f5e6c8",
     "members": [{"n": "アメス", "c": "#e58bb5"}, {"n": "シャビ・アロンソ", "c": "#FFFFFF"}], "idle": ["次の相談待ち"]},
    {"dept": "system-engineer", "label": "改修部", "color": "#cfe3f5",
     "members": [{"n": "デブライネ", "c": "#98C2E5"}, {"n": "花海咲季", "c": "#BA7278"}], "idle": []},
    {"dept": "product-scout", "label": "商品選定部", "color": "#e8d9f2",
     "members": [{"n": "十王星南", "c": "#b98be0"}, {"n": "クラウディア", "c": "#e0c06e"}], "idle": []},
    {"dept": "copy-director", "label": "コピー部", "color": "#d9f2df",
     "members": [{"n": "三笘薫", "c": "#5fae7a", "idle": "自主トレ中"},
                  {"n": "早坂芽衣", "c": "#f5c96e", "idle": "野良猫と会話中 / 昼寝中"}], "idle": []},
    {"dept": "shorts-analyst", "label": "分析部", "color": "#f5d9cf",
     "members": [{"n": "モドリッチ", "c": "#d98c66"}, {"n": "アーモンドアイ", "c": "#BAD4F4"}], "idle": []},
    {"dept": "qa-reviewer", "label": "品質管理部", "color": "#f2cfd9",
     "members": [{"n": "ジェンティルドンナ", "c": "#e08bab"}, {"n": "スネーク", "c": "#8ba3ab"}, {"n": "オタコン", "c": "#9bb5e0"}], "idle": []},
    {"dept": "learning-coach", "label": "学習室", "color": "#d9e8f2",
     "members": [{"n": "ヴィルシーナ", "c": "#4747CC", "idle": "お風呂中"}, {"n": "中野五月", "c": "#CA6558", "idle": "食事中"},
                  {"n": "田中琴葉", "c": "#8be0c9"}, {"n": "姫崎莉波", "c": "#f0b3d5", "idle": "着替え中"}], "idle": []},
    {"dept": "report-notify", "label": "報告・通知部", "color": "#e8f2cf",
     "members": [{"n": "オタコン(兼)", "c": "#9bb5e0"}, {"n": "メタルギアMk.II", "c": "#a3a3a3"}], "idle": []},
    {"dept": "kaizen-analyst", "label": "改善部", "color": "#e5e5e5",
     "members": [{"n": "(キャラ待ち)", "c": "#bbbbbb"}], "idle": []},
]


def d1(sql):
    r = subprocess.run(["npx", "wrangler", "d1", "execute", "go5_kaizen", "--remote", "--json", "--command", sql],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=os.path.join(ROOT, "fanza-worker"), shell=True, timeout=120)
    try:
        data = json.loads(r.stdout[r.stdout.index("["):])
        return data[0].get("results", [])
    except Exception:
        print("D1取得失敗:", (r.stdout or r.stderr)[:300])
        return []


def jst(ts):
    if not ts:
        return ""
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "").replace("T", " ").split(".")[0])
        return (t + datetime.timedelta(hours=9)).strftime("%m/%d %H:%M")
    except Exception:
        return str(ts)[:16]


def esc(s, n=70):
    s = str(s or "")
    return html.escape(s[:n] + ("…" if len(s) > n else ""))


def main():
    tasks = d1("SELECT assigned_dept,status,summary,result,created_at,completed_at FROM dept_tasks ORDER BY id DESC LIMIT 300")
    events = d1("SELECT created_at,event_type,source_dept,summary FROM dept_events ORDER BY id DESC LIMIT 25")
    chg = d1("SELECT COUNT(*) AS c FROM system_changes WHERE date(created_at)=date('now')")
    chg_today = chg[0]["c"] if chg else 0

    by = {}
    for t in tasks:
        by.setdefault(t["assigned_dept"], []).append(t)

    total_open = sum(1 for t in tasks if t["status"] in ("open", "in_progress"))
    utcnow = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    done_today = sum(1 for t in tasks if str(t.get("completed_at") or "").startswith(utcnow.strftime("%Y-%m-%d")))
    now_jst = (utcnow + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")

    rooms = []
    for r in ROSTER:
        ts = by.get(r["dept"], [])
        working = [t for t in ts if t["status"] == "in_progress"]
        opens = [t for t in ts if t["status"] == "open"]
        dones = [t for t in ts if t["status"] == "done"]
        blocked = [t for t in ts if t["status"] == "blocked"]
        acts = [t.get("completed_at") or t.get("created_at") for t in ts]
        acts += [e["created_at"] for e in events if e.get("source_dept") == r["dept"]]
        last_act = max([a for a in acts if a], default="")
        if working:
            bubble = "💬 " + esc(working[0]["summary"], 46)
            bubble_cls = "work"
        elif opens:
            bubble = f"📥 仕事箱に{len(opens)}件"
            bubble_cls = "queue"
        else:
            import random
            idles = [(m["n"], m["idle"]) for m in r["members"] if m.get("idle")]
            # 演出は「稀に」(Chami指定): 3割の確率でメンバー1人の待機演出、普段は素の待機
            if idles and random.random() < 0.3:
                who, act = random.choice(idles)
                bubble = f"🍵 {who}: {act} ※演出"
            elif r["idle"]:
                bubble = "🍵 " + r["idle"][0] + " ※演出"
            else:
                bubble = "🍵 待機中"
            bubble_cls = "idle"
        chips = "".join(
            f'<div class="chip"><span class="face" style="background:{m["c"]}">{html.escape(m["n"][0])}</span>'
            f'<span class="nm">{html.escape(m["n"])}</span></div>' for m in r["members"])
        detail_rows = ""
        for t in (working + blocked + opens)[:6]:
            detail_rows += f'<li>[{t["status"]}] {esc(t["summary"])}</li>'
        for t in dones[:3]:
            detail_rows += f'<li class="done">✅ {esc(t.get("result") or t["summary"])} <span class="ts">{jst(t.get("completed_at"))}</span></li>'
        if not detail_rows:
            detail_rows = "<li>記録なし(組織稼働2日目・これから溜まる)</li>"
        badges = ""
        if blocked:
            badges += f'<span class="badge bl">承認待ち{len(blocked)}</span>'
        if opens:
            badges += f'<span class="badge op">箱{len(opens)}</span>'
        rooms.append(f'''
<details class="room" style="background:{r["color"]}">
 <summary>
  <div class="rhead"><b>{html.escape(r["label"])}</b>{badges}</div>
  <div class="bubble {bubble_cls}">{bubble}</div>
  <div class="chips">{chips}</div>
  <div class="lastact">最終活動: {jst(last_act) or "—"}</div>
 </summary>
 <ul class="tasks">{detail_rows}</ul>
</details>''')

    tl = "".join(f'<li><span class="ts">{jst(e["created_at"])}</span> <b>{esc(e["source_dept"],18)}</b> '
                 f'{esc(e["event_type"],28)} — {esc(e["summary"],60)}</li>' for e in events) or "<li>イベントなし</li>"

    doc = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>go5 AIオフィス</title>
<style>
 body{{font-family:"MS Gothic","Yu Gothic",monospace;background:#2b2438;color:#222;margin:0;padding:14px}}
 h1{{color:#f5e6c8;font-size:18px;margin:2px 0 10px}} h1 small{{color:#b8a8d8;font-weight:normal;font-size:11px}}
 .summarybar{{background:#f5e6c8;border:3px solid #1c1826;border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px;display:flex;gap:18px;flex-wrap:wrap}}
 .ceo{{background:#ffe9a8;border:3px solid #1c1826;border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}}
 .room{{border:3px solid #1c1826;border-radius:8px;padding:10px;box-shadow:4px 4px 0 #1c1826}}
 .room summary{{cursor:pointer;list-style:none}}
 .rhead{{display:flex;align-items:center;gap:8px;font-size:14px;margin-bottom:6px}}
 .bubble{{background:#fff;border:2px solid #1c1826;border-radius:10px;padding:5px 9px;font-size:12px;display:inline-block;margin-bottom:8px}}
 .bubble.work{{background:#fff8d8}} .bubble.idle{{color:#666}}
 .chips{{display:flex;gap:10px;flex-wrap:wrap}}
 .chip{{text-align:center;font-size:10px}}
 .face{{display:block;width:34px;height:34px;border:2px solid #1c1826;border-radius:6px;margin:0 auto 3px;
        color:#fff;font-size:16px;line-height:32px;text-shadow:1px 1px 0 #1c1826}}
 .lastact{{font-size:10px;color:#555;margin-top:6px}}
 .badge{{font-size:10px;border:2px solid #1c1826;border-radius:6px;padding:1px 5px;background:#fff}}
 .badge.bl{{background:#ffd2d2}} .badge.op{{background:#d8ecff}}
 .tasks{{font-size:11px;background:#fff;border:2px solid #1c1826;border-radius:6px;margin:8px 0 0;padding:8px 8px 8px 24px}}
 .tasks .done{{color:#3a7a4a}} .ts{{color:#888;font-size:10px}}
 .timeline{{background:#e8e2f2;border:3px solid #1c1826;border-radius:8px;padding:10px;margin-top:14px}}
 .timeline h2{{font-size:13px;margin:0 0 6px}} .timeline ul{{margin:0;padding-left:18px;font-size:11px;line-height:1.7}}
 footer{{color:#b8a8d8;font-size:10px;margin-top:10px}}
</style></head><body>
<h1>🏢 go5-maker AIオフィス <small>DF-1 (偽Status禁止=全部D1の実データ) 最終更新 {now_jst} JST</small></h1>
<div class="summarybar"><span>📥 未完了タスク: <b>{total_open}</b></span><span>✅ 本日完了: <b>{done_today}</b></span><span>🔧 本日のCHG: <b>{chg_today}</b></span></div>
<div class="ceo">👑 <b>CEO室 — Chami</b>: 最終決定権はここ。各部屋クリックで仕事箱の中身が開く</div>
<div class="grid">{"".join(rooms)}</div>
<div class="timeline"><h2>📜 タイムライン(直近のできごと)</h2><ul>{tl}</ul></div>
<footer>ローカル専用・非公開 / 再生成: python scripts/office/build_office.py --open / 待機演出はキャラ設定由来の装飾で業務状態ではない</footer>
</body></html>'''

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"生成OK: {OUT} (部屋{len(rooms)}・タスク{len(tasks)}件参照)")
    if "--open" in sys.argv:
        os.startfile(OUT)


if __name__ == "__main__":
    main()
