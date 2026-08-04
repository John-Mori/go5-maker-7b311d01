#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_retro.py — 投稿動画の日次振り返り(分析部門・自室ツール)。
Chami依頼2026-08-04「毎日、昨日/一昨日/3日前に投稿された動画を振り返る」。

GAS(記録v2)から history(投稿履歴)と deltas(再生/クリック増分)を取得し、
直近に投稿された動画の再生数・題名の型を突き合わせて標準出力に振り返りを出す。
- history.videoId は内部post_id、deltas は実YouTube-idキー → youtubeUrlからidを抽出して突合。
- 再生の正= wv(週再生増。新規動画なら実質の累計再生)。★cc/cwc=クリック累計は再生ではない(混同禁止)。
- 出力はUTF-8固定(Windows端末のcp932でmojibakeしないように)。

使い方:  python scripts/analysis/daily_retro.py [--days 3]
"""
import json, io, re, sys, urllib.request
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

def exec_url():
    with open('scripts/gas_deploy_config.json', encoding='utf-8') as f:
        return json.load(f)['execUrl']

def jsonp_get(url):
    raw = urllib.request.urlopen(url, timeout=60).read().decode('utf-8')
    m = re.match(r'^x\((.*)\)\s*;?\s*$', raw.strip(), re.S)
    return json.loads(m.group(1) if m else raw)

def ytid(u):
    m = re.search(r'(?:shorts/|v=|youtu\.be/)([A-Za-z0-9_-]{11})', u or '')
    return m.group(1) if m else ''

def main():
    days = 3
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    base = exec_url()
    deltas = jsonp_get(f'{base}?action=deltas&callback=x')['deltas']
    rows = []
    for ch in ['acc1', 'acc2']:
        items = jsonp_get(f'{base}?action=history&channel={ch}&limit=80&callback=x').get('items', [])
        for it in items:
            try:
                dt = datetime.fromisoformat((it.get('postedAt') or '').replace('Z', '+00:00')).astimezone(JST)
            except Exception:
                continue
            dl = deltas.get(ytid(it.get('youtubeUrl')), {})
            rows.append((ch, dt, it, dl))
    rows.sort(key=lambda x: x[1], reverse=True)
    now = datetime.now(JST) if False else rows[0][1]  # 最新投稿日を基準(実行環境の時計に依存しない)
    today = datetime.now(JST).date()

    def emit(s=''):
        sys.stdout.buffer.write((s + '\n').encode('utf-8'))

    emit(f'# 投稿振り返り(基準日=最新投稿 {rows[0][1]:%m/%d} / 実行時JST {today})')
    emit('列: wv=週再生(新規は実質累計) / cc=累計導線1クリック / cwc=累計作品クリック  ★クリックと再生を混同しない')
    win = [(ch, dt, it, dl) for ch, dt, it, dl in rows if (today - dt.date()).days <= days]
    emit(f'\n## 直近{days}日以内の投稿 {len(win)}本')
    for ch, dt, it, dl in win:
        emit(f'  {dt:%m/%d %H:%M} {ch} wv={dl.get("wv")} cc={dl.get("cc")} cwc={dl.get("cwc")} | {it.get("title","")[:24]}')
    # 型別(問いかけ vs 断定)の直近30本比較
    import statistics as st
    last = [(dt, it.get('title', ''), dl.get('wv')) for ch, dt, it, dl in rows if isinstance(dl.get('wv'), (int, float))][:30]
    q = [r for r in last if re.search(r'[？?]', r[1])]
    nq = [r for r in last if not re.search(r'[？?]', r[1])]
    emit(f'\n## 題名の型(直近{len(last)}本・週再生)')
    if q:
        emit(f'  問いかけ形(？)  n={len(q)} 中央={st.median([r[2] for r in q])} 最大={max(r[2] for r in q)}')
    if nq:
        emit(f'  断定形(？なし)  n={len(nq)} 中央={st.median([r[2] for r in nq])} 最大={max(r[2] for r in nq)}')
    emit('\n## ブレイク上位5(週再生)')
    for dt, t, wv in sorted(last, key=lambda x: -x[2])[:5]:
        emit(f'  {wv:>7}  {t[:28]}')
    emit('## 不発下位5(週再生)')
    for dt, t, wv in sorted(last, key=lambda x: x[2])[:5]:
        emit(f'  {wv:>7}  {t[:28]}')

if __name__ == '__main__':
    main()
