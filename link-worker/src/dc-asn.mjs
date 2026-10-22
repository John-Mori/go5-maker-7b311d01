/**
 * dc-asn.mjs — データセンター(ホスティング)のASNか判定する（純粋関数・副作用なし）
 *
 * ★なぜ必要か★(gunji-5s 2026-10-23 依頼)
 *   short_click_log で、Hetzner(24940)のFirefox・Google Cloud(396982)のShapBot が counted に入っていた。
 *   UAはブラウザを名乗れるのでUAだけでは弾けない。人がスマホで踏む時の回線は家庭/携帯ISPで、
 *   クラウド事業者のASNから来るのは実質スクレイパ/監視/プレビュー生成。ここから来た分は数えない。
 *   ★302は返す(数えないだけ)。VPN経由の人が空白ページで詰まらないようにする。
 *
 * ★入れないもの★
 *   - Cloudflare(13335)・Akamai(36183)・Fastly(54113): iCloudプライベートリレー/WARPの出口で、
 *     iPhoneのSafariから来る人がここに乗る。外すと人を落とす。
 *   - 家庭/携帯ISP(Verizon 701 等): 人の回線。怪しい行は ASN ではなく別の材料で見る。
 */

const DATACENTER_ASNS = new Set([
  16509, 14618,   // Amazon AWS
  15169, 396982,  // Google / Google Cloud
  8075,           // Microsoft Azure
  31898,          // Oracle Cloud
  24940, 213230,  // Hetzner
  16276,          // OVH
  14061,          // DigitalOcean
  63949,          // Linode(Akamai Cloud)
  20473,          // Vultr(Choopa)
  51167,          // Contabo
  12876,          // Scaleway
  60781, 28753,   // LeaseWeb
  45102,          // Alibaba Cloud
  132203,         // Tencent Cloud
  9370, 7684,     // さくらインターネット
]);

/**
 * @param {number|string|null|undefined} asn - request.cf.asn
 * @returns {boolean} true＝データセンター(数えない)
 */
function isDatacenterASN(asn) {
  const n = Number(asn);
  return Number.isInteger(n) && DATACENTER_ASNS.has(n);
}

export { isDatacenterASN, DATACENTER_ASNS };
