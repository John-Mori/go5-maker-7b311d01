/**
 * D1 is primary so short-link traffic does not consume Workers KV writes.
 * KV remains read-compatible for links created before this migration.
 */
function changed_(result) {
  return Number(result && result.meta && result.meta.changes) || 0;
}

async function kvGet_(env, key) {
  if (!env.LINKS) return null;
  try { return await env.LINKS.get(key); } catch (e) { return null; }
}

export async function getLink(env, code) {
  if (env.LINKS_DB) {
    try {
      const row = await env.LINKS_DB.prepare(
        "SELECT url FROM short_links WHERE code = ?1"
      ).bind(code).first();
      if (row && row.url) return String(row.url);
    } catch (e) { /* legacy KV fallback */ }
  }
  return await kvGet_(env, "u:" + code);
}

export async function putLinkIfAbsent(env, code, url) {
  if (env.LINKS_DB) {
    try {
      const now = new Date().toISOString();
      await env.LINKS_DB.prepare(
        "INSERT OR IGNORE INTO short_links(code,url,clicks,created_at,updated_at) VALUES(?1,?2,0,?3,?3)"
      ).bind(code, url, now).run();
      const row = await env.LINKS_DB.prepare(
        "SELECT url FROM short_links WHERE code = ?1"
      ).bind(code).first();
      return row && row.url ? String(row.url) : null;
    } catch (e) { /* emergency KV write fallback */ }
  }
  if (!env.LINKS) return null;
  const existing = await kvGet_(env, "u:" + code);
  if (existing === null) {
    await env.LINKS.put("u:" + code, url);
    return url;
  }
  return existing;
}

export async function getClicks(env, code) {
  if (env.LINKS_DB) {
    try {
      const row = await env.LINKS_DB.prepare(
        "SELECT clicks FROM short_links WHERE code = ?1"
      ).bind(code).first();
      if (row) return Number(row.clicks) || 0;
    } catch (e) { /* legacy KV fallback */ }
  }
  return parseInt((await kvGet_(env, "c:" + code)) || "0", 10) || 0;
}

export async function bumpClickCount(env, code, url) {
  if (env.LINKS_DB) {
    try {
      const now = new Date().toISOString();
      const update = await env.LINKS_DB.prepare(
        "UPDATE short_links SET clicks = clicks + 1, updated_at = ?2 WHERE code = ?1"
      ).bind(code, now).run();
      if (changed_(update) > 0) return;

      // First access to a legacy KV link carries its historical count into D1.
      const legacyClicks = parseInt((await kvGet_(env, "c:" + code)) || "0", 10) || 0;
      const inserted = await env.LINKS_DB.prepare(
        "INSERT OR IGNORE INTO short_links(code,url,clicks,created_at,updated_at) VALUES(?1,?2,?3,?4,?4)"
      ).bind(code, url, legacyClicks + 1, now).run();
      if (changed_(inserted) === 0) {
        // Another isolate won the migration race; count this request once.
        await env.LINKS_DB.prepare(
          "UPDATE short_links SET clicks = clicks + 1, updated_at = ?2 WHERE code = ?1"
        ).bind(code, now).run();
      }
      return;
    } catch (e) { /* emergency KV write fallback */ }
  }

  if (!env.LINKS) return;
  const key = "c:" + code;
  const cur = parseInt((await kvGet_(env, key)) || "0", 10) || 0;
  await env.LINKS.put(key, String(cur + 1));
}

export async function consumeDailyIssue(env, day, limit) {
  if (env.LINKS_DB) {
    try {
      await env.LINKS_DB.prepare(
        "INSERT OR IGNORE INTO short_rate_limits(day,count) VALUES(?1,0)"
      ).bind(day).run();
      const result = await env.LINKS_DB.prepare(
        "UPDATE short_rate_limits SET count = count + 1 WHERE day = ?1 AND count < ?2"
      ).bind(day, limit).run();
      return changed_(result) > 0;
    } catch (e) { /* emergency KV write fallback */ }
  }

  if (!env.LINKS) return true;
  const key = "rl:" + day;
  const cur = parseInt((await kvGet_(env, key)) || "0", 10) || 0;
  if (cur >= limit) return false;
  await env.LINKS.put(key, String(cur + 1), { expirationTtl: 172800 });
  return true;
}

export async function listLinks(env, maxRows = 2000) {
  const merged = new Map();
  if (env.LINKS_DB) {
    try {
      const result = await env.LINKS_DB.prepare(
        "SELECT code,url,clicks FROM short_links ORDER BY clicks DESC LIMIT ?1"
      ).bind(maxRows).all();
      for (const row of (result && result.results) || []) {
        merged.set(String(row.code), {
          code: String(row.code), url: String(row.url || ""), clicks: Number(row.clicks) || 0,
        });
      }
    } catch (e) { /* legacy KV remains available */ }
  }

  if (env.LINKS && merged.size < maxRows) {
    const codes = [];
    let cursor;
    do {
      const result = await env.LINKS.list(cursor ? { prefix: "u:", cursor } : { prefix: "u:" });
      result.keys.forEach((key) => codes.push(key.name.slice(2)));
      cursor = result.list_complete ? null : result.cursor;
    } while (cursor && codes.length < maxRows);
    await Promise.all(codes.slice(0, maxRows).map(async (code) => {
      if (merged.has(code)) return;
      const [url, rawClicks] = await Promise.all([
        kvGet_(env, "u:" + code), kvGet_(env, "c:" + code),
      ]);
      merged.set(code, { code, url: url || "", clicks: parseInt(rawClicks || "0", 10) || 0 });
    }));
  }
  return Array.from(merged.values()).sort((a, b) => b.clicks - a.clicks).slice(0, maxRows);
}
