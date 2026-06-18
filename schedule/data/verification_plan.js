// 自動生成（scripts/build_app_data.py）。手で編集しない。
window.__VERIFICATION_PLAN__ = {
  "meta": {
    "name": "verification_plan",
    "purpose": "4週間検証（ABテスト）で schedule_master の verify_flag 枠と割れ枠（早夜vs深夜）を自チャンネル実データで確定する。",
    "version": "1.0",
    "last_updated": "2026-06-18",
    "source": "research/{claude,gemini,chatgpt}.md の検証章＋reference/okada_5sec.md を突合",
    "final_authority": "YouTube Studio『視聴者がアクセスしている時間帯』＝自チャンネル実データを一般論より優先",
    "principle": "時刻だけを変え、作品の強さ差をなるべく均す（同質の動画群を用いる）。スワイプ率<60%は時間帯でなく冒頭設計の問題として扱う。"
  },
  "measurement_points": [
    "1h",
    "3h",
    "6h",
    "24h",
    "48h"
  ],
  "kpis": [
    {
      "key": "shown_in_feed",
      "label": "Shortsフィード表示回数",
      "unit": "回",
      "capture_at": [
        "1h",
        "24h",
        "48h"
      ],
      "pass_threshold": null,
      "note": "初速の母数"
    },
    {
      "key": "viewed_rate",
      "label": "Viewed vs swiped away（スワイプ率/選択率）",
      "unit": "%",
      "capture_at": [
        "1h",
        "3h"
      ],
      "pass_threshold": ">=60",
      "ideal": ">=65",
      "note": "60%未満は冒頭設計の問題。枠判定から除外。"
    },
    {
      "key": "engaged_views",
      "label": "Engaged views",
      "unit": "回",
      "capture_at": [
        "1h"
      ],
      "pass_threshold": null
    },
    {
      "key": "avg_view_sec",
      "label": "平均視聴時間",
      "unit": "秒",
      "capture_at": [
        "3h",
        "24h"
      ],
      "pass_threshold": ">=9",
      "note": "5秒動画でループ2周到達の目安（okada）"
    },
    {
      "key": "avg_view_pct",
      "label": "平均視聴率",
      "unit": "%",
      "capture_at": [
        "3h"
      ],
      "pass_threshold": null
    },
    {
      "key": "retention",
      "label": "視聴維持率",
      "unit": "%",
      "capture_at": [
        "3h",
        "24h"
      ],
      "pass_threshold": ">=70"
    },
    {
      "key": "loop_rate",
      "label": "ループ率",
      "unit": "%",
      "capture_at": [
        "24h"
      ],
      "pass_threshold": null
    },
    {
      "key": "like_rate",
      "label": "高評価率",
      "unit": "%",
      "capture_at": [
        "3h",
        "24h"
      ],
      "pass_threshold": ">=3"
    },
    {
      "key": "comment_rate",
      "label": "コメント率",
      "unit": "%",
      "capture_at": [
        "3h",
        "24h"
      ],
      "pass_threshold": null
    },
    {
      "key": "saves",
      "label": "保存数",
      "unit": "件",
      "capture_at": [
        "24h",
        "48h"
      ],
      "pass_threshold": null
    },
    {
      "key": "profile_visits",
      "label": "プロフィール遷移率",
      "unit": "%",
      "capture_at": [
        "1h",
        "6h"
      ],
      "pass_threshold": null
    },
    {
      "key": "related_clicks",
      "label": "関連動画クリック",
      "unit": "件",
      "capture_at": [
        "6h",
        "24h"
      ],
      "pass_threshold": null
    },
    {
      "key": "profile_link_clicks",
      "label": "プロフィールリンククリック",
      "unit": "件",
      "capture_at": [
        "6h",
        "24h"
      ],
      "pass_threshold": null
    },
    {
      "key": "product_page_rate",
      "label": "作品詳細ページ遷移率",
      "unit": "%",
      "capture_at": [
        "6h",
        "24h",
        "48h"
      ],
      "pass_threshold": null,
      "note": "CVRの先行指標"
    },
    {
      "key": "sub_rate",
      "label": "チャンネル登録率",
      "unit": "%",
      "capture_at": [
        "24h",
        "48h"
      ],
      "pass_threshold": null
    },
    {
      "key": "ext_ctr",
      "label": "外部リンククリック率",
      "unit": "%",
      "capture_at": [
        "24h",
        "48h"
      ],
      "pass_threshold": null
    },
    {
      "key": "cvr",
      "label": "FANZA/DMM 成約率（承認範囲）",
      "unit": "%",
      "capture_at": [
        "48h"
      ],
      "pass_threshold": null,
      "note": "最終目的変数。母数小のため複数本で評価。"
    }
  ],
  "weeks": [
    {
      "week": 1,
      "theme": "基準作り（自チャンネルのピーク確定）",
      "design": "同質の動画を主要枠に固定配置。YouTube Studio『視聴者がアクセスしている時間帯』で自chピークを取得。",
      "fixed_slots": [
        "金=本命20:00",
        "土=本命21:00",
        "木=準本命20:00",
        "水=通常20:00",
        "火=昼テスト12:15"
      ],
      "variant_A": null,
      "variant_B": null,
      "primary_kpis": [
        "viewed_rate",
        "avg_view_sec",
        "profile_visits"
      ],
      "decision": "自chのアクセスピーク時刻を確定（以後の予約公開＝ピークの60–90分前の基準にする）。"
    },
    {
      "week": 2,
      "theme": "時間帯AB（割れ枠＝早夜 vs 深夜の決着）★最重要",
      "design": "金・土で同質動画を2群に分け、早夜公開 vs 深夜公開を比較。",
      "fixed_slots": [
        "金・土の本命枠を2系統で投下"
      ],
      "variant_A": {
        "label": "早夜系（初期採用）",
        "publish": {
          "金": "20:00–20:30",
          "土": "21:00–21:30"
        }
      },
      "variant_B": {
        "label": "深夜系（alt）",
        "publish": {
          "金": "22:30",
          "土": "22:00"
        }
      },
      "primary_kpis": [
        "product_page_rate",
        "ext_ctr",
        "cvr",
        "viewed_rate"
      ],
      "decision": "48h成約率/作品詳細遷移率が安定して優位な系統を schedule_master の本命 time に確定（敗者は alt へ）。"
    },
    {
      "week": 3,
      "theme": "曜日AB ＋ 平日成約比率の検証",
      "design": "同一フォーマットを 金/土/木/日 に配置し曜日差を比較。並行して平日21時の準本命を増やした日(成約系33%)と通常の日(17%)を比較（okada由来・要確認①）。",
      "fixed_slots": [
        "金/土/木/日に同質動画",
        "平日：準本命+1あり/なし"
      ],
      "variant_A": {
        "label": "平日 成約系17%（現行）"
      },
      "variant_B": {
        "label": "平日 成約系33%（準本命+1）"
      },
      "primary_kpis": [
        "cvr",
        "like_rate",
        "sub_rate"
      ],
      "decision": "曜日別の本命優先度を確定。平日比率17%/33%のうち成約効率の高い方を採用。"
    },
    {
      "week": 4,
      "theme": "フック・導線AB（勝ち枠で再現性確認）",
      "design": "勝った枠に、冒頭1コマ目・フック文を変えた2パターンを投下（冒頭離脱・スワイプ率の差）。並行して導線AB（関連動画ブリッジ vs プロフィール直リンク）。",
      "fixed_slots": [
        "勝ち枠（例：金20:00）に本命候補を再投入"
      ],
      "variant_A": {
        "label": "導線：関連動画(ブリッジ長尺)経由"
      },
      "variant_B": {
        "label": "導線：プロフィール直リンク経由"
      },
      "primary_kpis": [
        "viewed_rate",
        "ext_ctr",
        "product_page_rate",
        "cvr"
      ],
      "decision": "冒頭フックの勝ちパターンと最適導線を確定。schedule_master の verify_flag を解除。"
    }
  ],
  "decision_rules": [
    {
      "target": "divided_slot（金/土 本命の公開時刻）",
      "rule": "Week2で 48h成約率 or 作品詳細遷移率 が片系統に安定優位。3週連続で深夜>早夜なら深夜へ昇格（Claude閾値）。",
      "action": "schedule_master.templates[休前日型/連休中日型] の本命 time を勝者へ、alt_hypothesis を敗者へ。verify_flag=false。"
    },
    {
      "target": "枠の本命昇格",
      "rule": "同一フックでも枠により 48h再生が2倍以上違えば、その枠を本命に昇格（Claude）。",
      "action": "該当 day-type の slot role を本命へ。"
    },
    {
      "target": "冒頭設計の切り分け",
      "rule": "スワイプ率<60%（理想<65%）の動画は時間帯ではなく冒頭設計の問題として、枠評価の母集団から除外。",
      "action": "フック改善タスクへ（時間帯判定に使わない）。"
    },
    {
      "target": "平日成約系比率（要確認①）",
      "rule": "Week3の 17% vs 33% で 成約効率（cvr/投下本数）が高い方を採用。",
      "action": "平日型テンプレの slot3(準本命) を維持 or 通常枠を1つ準本命へ。"
    }
  ],
  "log_columns": [
    "log_id",
    "video_id",
    "slot_id",
    "date",
    "day_type",
    "role",
    "genre",
    "variant",
    "publish_time",
    "week",
    "measured_at",
    "shown_in_feed",
    "viewed_rate",
    "engaged_views",
    "avg_view_sec",
    "avg_view_pct",
    "retention",
    "loop_rate",
    "like_rate",
    "comment_rate",
    "saves",
    "profile_visits",
    "related_clicks",
    "profile_link_clicks",
    "product_page_rate",
    "sub_rate",
    "ext_ctr",
    "fanza_clicks",
    "cvr",
    "note"
  ]
};
