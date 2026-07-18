/**
 * deadman-worker — 外部dead-man (恒久-1の外部半分・2026-07-18)。
 *
 * 役割: 家PCが健全な間だけ deadman_check.py が POST /beat を打つ。ビートが STALE_MIN 分を超えて
 *       途絶えたら、cron(15分毎)がそれを検知し Discord webhook へ「PCごと停止」通知を1回だけ出す。
 *       ビートが再開したら復帰通知を1回だけ出す。= PC自身が走れない状態(ロック画面/再起動/電源断=
 *       logon-gap)を、PCの外から見張る。ローカルの艦隊dead-man(deadman_check.py)が
 *       「PC生存時のsupervisor死」を見るのと相補。
 *
 * エンドポイント:
 *   POST /beat   (ヘッダ X-Beat-Secret == BEAT_SECRET)  → KV last_beat=now, alerted=削除, 204
 *   GET  /status                                        → {last_beat, age_sec, alerted} (点検用・秘密不要)
 * cron(scheduled): last_beat の鮮度を見て、閾値超過で通知(alertedで連投防止)、回復で復帰通知。
 *
 * 秘密: BEAT_SECRET(PC側と共有) / DISCORD_WEBHOOK(既存webhookを再利用)。KV binding=DEADMAN。
 * 非破壊: 自KVと1webhookのみ。他へ一切書かない。
 */

const K_LAST = 'last_beat';   // 最終ビートのepoch ms(文字列)
const K_ALERTED = 'alerted';  // '1' の間は停止通知済み(連投防止)

async function postDiscord(webhook, content) {
  if (!webhook) return false;
  try {
    const r = await fetch(webhook, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, allowed_mentions: { parse: [] } }),
    });
    return r.ok || r.status === 204;
  } catch (e) {
    return false;
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/beat') {
      const secret = request.headers.get('X-Beat-Secret') || '';
      if (!env.BEAT_SECRET || secret !== env.BEAT_SECRET) {
        return new Response('forbidden', { status: 403 });
      }
      await env.DEADMAN.put(K_LAST, String(Date.now()));
      // 停止中に復帰したら、次のcronを待たずここでも復帰通知を出して alerted を落とす。
      const wasAlerted = (await env.DEADMAN.get(K_ALERTED)) === '1';
      if (wasAlerted) {
        await postDiscord(env.DISCORD_WEBHOOK, '✅ go5-PC 復帰 — ハートビートが再開しました(PC/常駐が復旧)。');
        await env.DEADMAN.delete(K_ALERTED);
      }
      return new Response(null, { status: 204 });
    }

    if (request.method === 'GET' && url.pathname === '/status') {
      const last = parseInt((await env.DEADMAN.get(K_LAST)) || '0', 10);
      const alerted = (await env.DEADMAN.get(K_ALERTED)) === '1';
      const age_sec = last ? Math.round((Date.now() - last) / 1000) : null;
      return new Response(JSON.stringify({ last_beat: last || null, age_sec, alerted }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    return new Response('deadman-worker', { status: 404 });
  },

  async scheduled(event, env, ctx) {
    const staleMin = parseInt(env.STALE_MIN || '35', 10);
    const last = parseInt((await env.DEADMAN.get(K_LAST)) || '0', 10);
    const alerted = (await env.DEADMAN.get(K_ALERTED)) === '1';

    // まだ一度もビートが無い(初期化前)なら何もしない=誤報を出さない。
    if (!last) return;

    const ageMin = (Date.now() - last) / 60000;

    if (ageMin > staleMin) {
      if (!alerted) {
        const mins = Math.round(ageMin);
        const ok = await postDiscord(
          env.DISCORD_WEBHOOK,
          `🚨 **go5-PC 応答なし** — ハートビートが${mins}分途絶(閾値${staleMin}分)。\n` +
          `家PCがロック画面/再起動/電源断などで停止し、ローカルの常駐(受信・応答・監視)がすべて動いていない可能性。\n` +
          `※この通知はPCの外(Cloudflare)から出しています。PCが復旧すれば自動で復帰通知します。`
        );
        // ★送信に成功した時だけ alerted を立てる。失敗時は立てない=次のcron(15分後)が再送する。
        //   (送信失敗でも立てると、webhook不通の瞬間に鳴らそうとした唯一のアラートが永久に失われる)
        if (ok) await env.DEADMAN.put(K_ALERTED, '1');
      }
    } else if (alerted) {
      // 閾値内に戻った=復帰(POST /beat 側で拾えなかった場合の保険)。
      await postDiscord(env.DISCORD_WEBHOOK, '✅ go5-PC 復帰 — ハートビートが閾値内に戻りました。');
      await env.DEADMAN.delete(K_ALERTED);
    }
  },
};
