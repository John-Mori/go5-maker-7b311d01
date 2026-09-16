#!/usr/bin/env python3
"""Discord webhookへ画像ファイルを1枚添付送信する。"""
import json, sys, os, requests

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOCAL = os.path.join(ROOT, 'local')

def send_image(channel_id, persona, img_path, caption=''):
    with open(os.path.join(LOCAL, 'discord_webhooks_auto.json'), encoding='utf-8') as f:
        hooks = json.load(f)
    webhook_url = hooks.get(str(channel_id))
    if not webhook_url:
        print(f'ERROR: webhook not found for channel {channel_id}', file=sys.stderr)
        return False

    try:
        with open(os.path.join(LOCAL, 'persona_avatars.json'), encoding='utf-8') as f:
            avatars = json.load(f)
        avatar_url = avatars.get(persona, '')
    except Exception:
        avatar_url = ''

    fname = os.path.basename(img_path)
    with open(img_path, 'rb') as f:
        img_data = f.read()

    data = {'username': persona}
    if avatar_url:
        data['avatar_url'] = avatar_url
    if caption:
        data['content'] = caption

    files = {'files[0]': (fname, img_data, 'image/png')}
    # ★2026-09-16 イージス研究室: wait=true= 204(本文なし)だと msg_id が取れず、
    #   台帳の1行から実物の投稿へ辿り直せない(中野五月 DISPATCH-aegis-gl-1789568669959)。
    url = webhook_url + ('&' if '?' in webhook_url else '?') + 'wait=true'
    resp = requests.post(url, data=data, files=files, timeout=20)
    msg_id = ''
    try:
        msg_id = str(resp.json().get('id') or '')
    except Exception:
        pass
    # ★画像便もDiscordのOUT口だ。send_audit の docstring は「撃つのは bot_send と
    #   persona_send の2箇所だけ」と書いているが、画像便2本はその数え落としだった
    #   = ここと scripts/imagegen/generate.py:discord_upload。記録先は増やさない(ORG-11)。
    try:
        import send_audit
        send_audit.record('send_image', body=caption, status=resp.status_code,
                          channel_id=str(channel_id), persona=persona, msg_id=msg_id)
    except Exception:
        pass                                     # fail-open= 台帳の1行で投稿を殺さない
    if resp.status_code in (200, 204):
        print(f'OK HTTP {resp.status_code}' + (f' msg={msg_id}' if msg_id else ''))
        return True
    else:
        print(f'ERROR HTTP {resp.status_code}: {resp.text[:200]}', file=sys.stderr)
        return False

if __name__ == '__main__':
    # 引数: channel_id persona img_path [caption]
    if len(sys.argv) < 4:
        print('Usage: send_image.py <channel_id> <persona> <img_path> [caption]')
        sys.exit(1)
    ch = sys.argv[1]
    persona = sys.argv[2]
    img = sys.argv[3]
    cap = sys.argv[4] if len(sys.argv) > 4 else ''
    sys.exit(0 if send_image(ch, persona, img, cap) else 1)
