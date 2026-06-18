// 自動生成（scripts/build_app_data.py）。手で編集しない。
window.__SCHEDULE_MASTER__ = {
  "meta": {
    "name": "schedule_master",
    "purpose": "day-type別の最適公開時刻・ピーク・枠・採用ジャンル傾向。slots生成のテンプレート正本。",
    "version": "0.2-crosschecked",
    "status": "突合実施済み（§6 #1〜#3完了）。verify_flag枠は4週間検証で確定。",
    "last_updated": "2026-06-18",
    "verify_policy": "verify_flag=true の枠は4週間検証（YouTube Studio実データ）で上書きする前提。",
    "divided_slot_decision": {
      "issue": "§11-⑤ 金曜/土曜 本命の公開時刻（早夜系 vs 深夜系）",
      "chosen": "早夜系（金=公開20:00–20:30 / 土=公開21:00–21:30）",
      "rationale": "突合で2:1の多数派（Claude/GPT＝早夜公開、Gemini＝深夜22:30公開）。3AIとも『23:00–01:00が成約(CVR)の最良窓』では一致しており、早夜公開は『20時台に出して21–23時の初速→23–01時の私的遷移を両取り』する収益戦略。よって収益性優先とも矛盾しない。",
      "alt_hypothesis": "深夜系（金=22:30公開/23:30–01:30ピーク[Gemini]、土=22:00公開）。",
      "agreement": "2:1。Week2の時間帯ABで確定。",
      "note_prev": "暫定版(v0.1)では収益性優先で深夜系を初期採用していたが、突合の多数派＋CVR窓の共通認識を踏まえ早夜系へ更新。深夜系はalt保持。"
    },
    "data_inputs": {
      "research_3ai": "research/{claude,gemini,chatgpt}.md（突合済み：work/extract_table.md, work/crosscheck_matrix.md）",
      "okada": "reference/okada_5sec.md（反映済み：funnel/picture/ban）"
    },
    "common_agreements": [
      "金=最強(本命日)、土=本命/準本命、木=準本命の最優先、日=関心形成(本命にしない)、平日=通常・母数稼ぎ",
      "23:00–01:00が成約(CVR)の最良窓（私的・就寝前視聴）",
      "昼12時台は認知/登録の入口・成約期待しない",
      "深夜2時以降は本命にしない（母数不足）",
      "規制は時間帯でなく表現で決まる／年齢制限を回避",
      "冒頭1秒・1コマ目・フックが最重要（時刻は最後の上積み）",
      "祝前日→金曜型 / 連休中日→土曜型 / 連休最終日→日曜型",
      "通知は24h最大3件→本命前後を詰め込み過ぎない"
    ]
  },
  "publish_timing": {
    "rule": "ピークの約60–90分前に予約公開（本命は90–120分前）。初速(1h/3h/6h/24h/48h)で評価。",
    "swipe_rate_pass": "Viewed vs swiped away ≥ 60%（理想65–70%）",
    "final_authority": "YouTube Studio『視聴者がアクセスしている時間帯』＝自チャンネル実データを一般論より優先"
  },
  "funnel_policy": {
    "source": "okada §6（1ch 8本中 3〜4本=成約狙い）＋3AI突合",
    "principle": "売れやすい作品≠再生されやすい動画。成約系と集客系を分けて管理する。",
    "role_to_funnel": {
      "本命": "成約系",
      "準本命": "成約系",
      "通常": "集客系",
      "昼補助": "集客系",
      "深夜補助": "集客系",
      "テスト": "集客系"
    },
    "cta_routing": "概要欄/コメントの直URLはクリック不可(2023/8〜・Gemini/GPT)。導線は『Shorts→関連動画(ブリッジ長尺)→プロフィールリンク』を主にする。",
    "daily_target_hint": {
      "本命日(金土)": "成約系50%",
      "平日": "成約系17%(検討:33%)",
      "週平均": "35%前後"
    }
  },
  "picture_guide": {
    "source": "okada §3-§5 ＋ 3AI(冒頭設計)",
    "choose": [
      "意味を考えたくなる(数字/状況)→滞在時間↑",
      "自分事の選択(AとBどっち?)→コメント/エンゲージ↑",
      "続きが気になる表示(1年後/この後〇〇・一部を隠す。過激すぎない範囲)",
      "人気アニメ風・異世界系(親和性高くスクロールが止まる)",
      "露骨さでなく『異変』で止める：表情の違和感/セリフの破壊力/バレたら終わる状況/立場の逆転"
    ],
    "avoid": [
      "喘ぎ声・擬音だけ(引きが弱い)",
      "欲求を掻き立てない(精子卵子・普通の結婚式)",
      "胸の強調(色/白黒問わずフィード非掲載=シャドウバン)",
      "過度な露出(足・太もも・パンチラの強調)",
      "リスクの高い構図(レンズ越しの覗き等:隠すと意味不明/隠さないとNG)",
      "露骨な性的行為を想起させる語・卑猥語・性的満足を直球で煽るコピー"
    ],
    "layout": "中央=目立つ画像(続きが気になる文章入り) / 上部=気を引くコメント(上1/3の安全領域に太字) / 背景・作者名は画像内 / 下部マスコット等は使わずシンプル"
  },
  "ban_guide": {
    "source": "okada §3質疑・§10 ＋ 3AI(規制章)",
    "principle": "規制は時間帯でなく表現で決まる。深夜投稿で審査が甘くなる公式根拠は無い。露出/強調を避け、直接誘導文も避ける。",
    "age_restriction_impact": "年齢制限が付くとサインアウト/18歳未満/制限モードで非表示＋Shortsフィード推薦遮断＋チャンネル全体にデバフ。本命ほど回避必須。",
    "cta_policy": "動画内・タイトルに『作品は概要欄から』等の直接誘導文を入れない(BANリスク)。文言は『続き/詳細/作品情報/レビュー』寄りに。",
    "kpi_baseline": "平均視聴≧9秒(=5秒動画でループ2周到達=画像選定成功の目安・okada §7)"
  },
  "slot_layout": [
    {
      "slot_index": 0,
      "label": "昼補助",
      "default_time": "12:15"
    },
    {
      "slot_index": 1,
      "label": "夕方",
      "default_time": "18:00"
    },
    {
      "slot_index": 2,
      "label": "夜前半(20時)",
      "default_time": "20:00"
    },
    {
      "slot_index": 3,
      "label": "夜ピーク帯(21時)",
      "default_time": "21:00"
    },
    {
      "slot_index": 4,
      "label": "深夜前半(23時=CVR窓)",
      "default_time": "23:00"
    },
    {
      "slot_index": 5,
      "label": "深夜補助(24時)",
      "default_time": "24:00"
    }
  ],
  "genre_hints": {
    "本命_金": "NTR・人妻・背徳・寝取られ系（露骨でなく続きが気になる型）",
    "本命_土": "ギャル・ハーレム・誘惑系（視覚重視）/ 展開・オチが気になる型",
    "準本命": "先生/先輩/上司系・シリアス・復讐系",
    "通常": "純愛・アオハル・コメディ・ギャル系（集客・読後感重視）",
    "テスト": "新規・特殊導入・復讐/シリアス検証",
    "昼補助": "音なしで伝わるコメディ・1コマ強い系",
    "深夜補助": "復讐・シリアス・ニッチ（コア層検証）"
  },
  "templates": {
    "平日型": {
      "label": "平日型（月〜水・通常・母数稼ぎ）",
      "agreement": "3AI合意（平日=通常中心）。21時台ピークは検証。",
      "slots": [
        {
          "slot_index": 0,
          "time": "12:15",
          "role": "昼補助",
          "genre_hint": "音なしで伝わるコメディ・1コマ強い系",
          "peak": "認知/登録の入口（成約期待しない）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 1,
          "time": "18:00",
          "role": "通常",
          "genre_hint": "純愛・アオハル・コメディ・ギャル系",
          "peak": "—",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 2,
          "time": "20:00",
          "role": "通常",
          "genre_hint": "純愛・アオハル・コメディ・ギャル系",
          "peak": "帰宅後私的時間",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 3,
          "time": "21:00",
          "role": "準本命",
          "genre_hint": "先生/先輩/上司系・シリアス・復讐系",
          "peak": "21:00–23:00（就寝前没入）",
          "verify_flag": true,
          "alt_hypothesis": "平日成約系比率を17%→33%へ上げる案（okada由来・要確認①）"
        },
        {
          "slot_index": 4,
          "time": "23:00",
          "role": "通常",
          "genre_hint": "純愛・アオハル・コメディ・ギャル系",
          "peak": "深夜CVR窓に接続",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 5,
          "time": "24:00",
          "role": "深夜補助",
          "genre_hint": "復讐・シリアス・ニッチ（コア層検証）",
          "peak": "コア層検証（母数小・2時以降は本命にしない）",
          "verify_flag": false,
          "alt_hypothesis": null
        }
      ]
    },
    "休前日型": {
      "label": "休前日型（=金曜/祝前日・本命日）",
      "agreement": "本命公開=早夜系を2:1で採用（深夜系はalt）。CVR窓23:00–01:00は3AI合意。",
      "slots": [
        {
          "slot_index": 0,
          "time": "12:15",
          "role": "昼補助",
          "genre_hint": "音なしで伝わるコメディ・1コマ強い系",
          "peak": "認知/登録の入口（成約期待しない）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 1,
          "time": "18:00",
          "role": "通常",
          "genre_hint": "純愛・アオハル・コメディ・ギャル系",
          "peak": "—",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 2,
          "time": "20:00",
          "role": "本命",
          "genre_hint": "NTR・人妻・背徳・寝取られ系（露骨でなく続きが気になる型）",
          "peak": "公開20:00→21:00–24:00初速→CVR窓23:00–01:00へ伸長",
          "verify_flag": true,
          "alt_hypothesis": "深夜系: 22:30公開 / 23:30–01:30ピーク（Gemini）"
        },
        {
          "slot_index": 3,
          "time": "21:00",
          "role": "準本命",
          "genre_hint": "先生/先輩/上司系・シリアス・復讐系",
          "peak": "21時台 初速の上積み",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 4,
          "time": "23:00",
          "role": "準本命",
          "genre_hint": "NTR・人妻・背徳系（深夜の私的遷移狙い）",
          "peak": "深夜CVR窓 23:00–01:00（3AI合意）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 5,
          "time": "24:00",
          "role": "深夜補助",
          "genre_hint": "復讐・シリアス・ニッチ（コア層検証）",
          "peak": "コア層検証（母数小・2時以降は本命にしない）",
          "verify_flag": false,
          "alt_hypothesis": null
        }
      ]
    },
    "連休初日型": {
      "label": "連休初日型（土寄り・橋渡し。旅行/交流優先で深夜に一時増）",
      "agreement": "準本命中心の橋渡し（Gemini）。本命昇格は検証。",
      "slots": [
        {
          "slot_index": 0,
          "time": "12:15",
          "role": "昼補助",
          "genre_hint": "音なしで伝わるコメディ・1コマ強い系",
          "peak": "認知/登録の入口（成約期待しない）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 1,
          "time": "18:00",
          "role": "通常",
          "genre_hint": "ギャル・ハーレム・誘惑系（キャッチー）",
          "peak": "—",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 2,
          "time": "20:00",
          "role": "準本命",
          "genre_hint": "先生/先輩/上司系・シリアス・復讐系",
          "peak": "—",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 3,
          "time": "21:00",
          "role": "準本命",
          "genre_hint": "先生/先輩/上司系・シリアス・復讐系",
          "peak": "21時台",
          "verify_flag": true,
          "alt_hypothesis": "本命に昇格させる案あり（連休初日の深夜急増を取りに行く・検証）"
        },
        {
          "slot_index": 4,
          "time": "23:00",
          "role": "準本命",
          "genre_hint": "NTR・人妻・背徳系（深夜の私的遷移狙い）",
          "peak": "深夜CVR窓 23:00–01:00",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 5,
          "time": "24:00",
          "role": "深夜補助",
          "genre_hint": "復讐・シリアス・ニッチ（コア層検証）",
          "peak": "コア層検証（母数小・2時以降は本命にしない）",
          "verify_flag": false,
          "alt_hypothesis": null
        }
      ]
    },
    "連休中日型": {
      "label": "連休中日型（=土曜・本命日）",
      "agreement": "本命公開=早夜系(21時台)を2:1で採用（深夜22:00はalt）。ピーク22:00–翌1:00は3AIほぼ一致。",
      "slots": [
        {
          "slot_index": 0,
          "time": "12:15",
          "role": "昼補助",
          "genre_hint": "音なしで伝わるコメディ・1コマ強い系",
          "peak": "認知/登録の入口（成約期待しない）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 1,
          "time": "18:00",
          "role": "通常",
          "genre_hint": "ギャル・ハーレム・誘惑系（視覚重視）",
          "peak": "—",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 2,
          "time": "20:00",
          "role": "準本命",
          "genre_hint": "先生/先輩/上司系・シリアス・復讐系",
          "peak": "—",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 3,
          "time": "21:00",
          "role": "本命",
          "genre_hint": "ギャル・ハーレム・誘惑系（視覚重視）/ 展開・オチが気になる型",
          "peak": "公開21:00→22:00–翌1:00ピーク（CVR窓と接続）",
          "verify_flag": true,
          "alt_hypothesis": "深夜系: 22:00公開（Gemini）"
        },
        {
          "slot_index": 4,
          "time": "23:00",
          "role": "準本命",
          "genre_hint": "NTR・人妻・背徳系（深夜の私的遷移狙い）",
          "peak": "深夜CVR窓 23:00–01:00（3AI合意）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 5,
          "time": "24:00",
          "role": "深夜補助",
          "genre_hint": "復讐・シリアス・ニッチ（コア層検証）",
          "peak": "コア層検証（母数小・2時以降は本命にしない）",
          "verify_flag": false,
          "alt_hypothesis": null
        }
      ]
    },
    "最終日型": {
      "label": "最終日型（=日曜/連休最終日・関心形成。本命を置かない）",
      "agreement": "3AI合意（本命にしない）。最適公開は18:45–22:00で割れ→20時前後で運用・検証。",
      "slots": [
        {
          "slot_index": 0,
          "time": "12:15",
          "role": "昼補助",
          "genre_hint": "音なしで伝わるコメディ・1コマ強い系",
          "peak": "認知/登録の入口（成約期待しない）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 1,
          "time": "18:00",
          "role": "通常",
          "genre_hint": "純愛・アオハル（読後感の良い王道）",
          "peak": "—",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 2,
          "time": "20:00",
          "role": "通常",
          "genre_hint": "純愛・アオハル（日曜トラフィック回収）",
          "peak": "20:00–22:00（巨大トラフィック・深追いされにくい）",
          "verify_flag": false,
          "alt_hypothesis": null
        },
        {
          "slot_index": 3,
          "time": "21:00",
          "role": "通常",
          "genre_hint": "純愛・アオハル・コメディ系",
          "peak": "21:30–23:00（23時以降は購買意欲減退）",
          "verify_flag": true,
          "alt_hypothesis": "公開を18:45–19:15へ早める案（GPT）/ 20:30（Gemini）"
        },
        {
          "slot_index": 4,
          "time": "23:00",
          "role": "テスト",
          "genre_hint": "復讐・シリアス・特殊設定（続きが気になる構成）",
          "peak": "深夜の深掘り層（捨て打ち・検証）",
          "verify_flag": true,
          "alt_hypothesis": null
        },
        {
          "slot_index": 5,
          "time": "24:00",
          "role": "深夜補助",
          "genre_hint": "復讐・シリアス・ニッチ（コア層検証）",
          "peak": "コア層検証（母数小・2時以降は本命にしない）",
          "verify_flag": false,
          "alt_hypothesis": null
        }
      ]
    }
  }
};
