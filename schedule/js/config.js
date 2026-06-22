// config（設計書 §9：上書き可能項目）
// すべてのモジュールが参照する単一の設定オブジェクト。UIから一部を変更可能。
window.SCH = window.SCH || {};

SCH.config = {
  // 長期休暇レンジ（明示が要るのは年末年始・お盆だけ。GW/SWは祝日CSV＋週末で自動成立）
  longVac: {
    newyear: { start: "12-29", end: "01-03", label: "年末年始", tag: "newyear" }, // 6連休基準
    obon:    { start: "08-13", end: "08-16", label: "お盆",     tag: "obon"     }, // 山の日(8/11)は祝日側
  },
  bridgeWeekdayAsDayOff: false, // GW/SW 橋渡し平日を休扱いにするか（既定OFF・§9）
  alwaysFridayType: true,       // 祝前日を常に休前日(金曜)型に（既定ON・§9）
  slotsPerDay: 6,               // 1日本数（既定6・§9）
  generateWeeksAhead: 9,        // 生成期間：当日から約2ヶ月先（8〜9週・§7.7）
  displayWeeks: 5,              // 表示：当日週(月曜起点)から5週（§7.7/§7.9）
  protectConfirmedSlots: true,  // 予約済/公開済は時刻自動変更しない（要確認のみ・§7.5/§9）
  recalcScope: "run",           // 再計算範囲：連続ラン＋前後1日（§7.5）

  // アカウント別の投稿時刻オフセット（分）。acc2 をずらして2アカウント同時刻を避ける（リサーチ：明確な最短値の確証は無いため初期値20分・調整可）。
  accountOffsetMin: { acc1: 0, acc2: 20 },

  // ステータス enum（§7.6）
  statusEnum: ["未着手", "制作済・未予約", "予約登録済", "公開済", "取り下げ"],
  // 自動更新の対象になる空き枠（§7.5：未着手 / 制作済・未予約 のみ）
  autoUpdatableStatuses: ["未着手", "制作済・未予約"],
};

// 永続化アダプタ選択（§7.8）。'local' は開発用プレースホルダ。
// クラウドDB（Supabase等）導入時に 'supabase' へ切替（store.js 参照）。
// ※ localStorage を正本にはしない方針。クラウド導入までの暫定。
SCH.config.persistence = {
  adapter: "local",
  supabase: { url: "", anonKey: "", table: "slots" }, // 鍵はリポジトリに直書きしない（§12.3）
};
