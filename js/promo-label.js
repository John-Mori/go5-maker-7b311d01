/**
 * promo-label.js — 販促ラベル(セールラベル)
 *
 * 2026-07-16 作り替え(Chami指示・指示書「セールラベル数値可変化」):
 *   Chami提供の完成デザインPNG(数字なしテンプレ)を敷き、数字だけをコードで描く。
 *   - テンプレは4種: 月詠み(acc1)×[割引率/価格] / 宵桜(acc2)×[割引率/価格]。
 *   - 固定文言(今なら/%OFF/月影に綴る/¥/作品案内…)は全てPNG側に焼き込み済み=コードでは触らない。
 *   - 数字は指示書の通り「数字領域(slot)の中央」へ。1〜3桁は幅に合わせ自動縮小。
 *   - 不正値(0/負/NaN/未設定)はラベルごと非表示。定価(セールでない)も非表示。
 *   - 数字の質感はCanvas描画で原画に合わせる(提供された数字シートは背景が焼き込みで
 *     切り出すと継ぎ目が出るため不採用。シートは local/promo-ref/ に保管=将来の精密化用)。
 *
 * 2026-07-15の設計を継承: 写真への焼き込みはせず、動画フレーム(1080×1920)への重ね描き。
 *   app.js の drawFrame() が Go5PromoLabel.drawOverlay() を呼ぶ。プレビュー=書き出し一致。
 *   位置はフレーム比(0..1)、大きさは倍率。D-pad+指ドラッグで調整、localStorageで永続。
 */
(function () {
  'use strict';
  // ★テンプレPNGはindex.htmlの<script src>ではなくJSからsrc指定で読むため bump.mjs の ?v= が乗らない。
  //   同名PNGの中身を差し替えても(2026-08-10 月詠み価格札の再生成など)キャッシュで古い絵が出る。
  //   → 自分のscriptに付いた ?v=N を拾って画像URLへ引き継ぐ=版バンプでPNGも必ずキャッシュ更新される。
  //   currentScriptは同期実行中のみ有効なのでIIFE先頭で捕まえる(index.htmlのref検査には出ない=smoke無影響)。
  var _ASSET_VER = (function () {
    try { var s = (document.currentScript && document.currentScript.src) || ''; var m = s.match(/[?&]v=(\d+)/); return m ? m[1] : ''; }
    catch (e) { return ''; }
  })();
  function _bust(url) { return _ASSET_VER && url ? url + (url.indexOf('?') < 0 ? '?' : '&') + 'v=' + _ASSET_VER : url; }
  var FRAME_W = 1080, FRAME_H = 1920;
  // 帯フォールバック用の基本寸法(テンプレPNGが読めない間のみ使用・フレーム基準)。
  var LBL = { w: 335, h: 79, font: 46, radius: 18 };

  // ── テンプレート定義 ──
  // slot = 数字を置く領域(画像内の比率)。基材PNGの画素解析で確定した値(2026-07-16):
  //   ・月詠み割引: 「今なら」(行331-436)と「%OFF」(行781-)の間の空き
  //   ・月詠み価格: 仕切り(〜754)と「作品」(995-)の間・¥の右側
  //   ・宵桜割引: 「今だと」(列〜753)と「%OFF」(列1292-)の間
  //   ・宵桜価格: 「今宵の¥」(列〜848)と「作品案内」(列1297-)の間
  // ink = 数字の色(グラデ上/下・縁・光彩)。原画の数字(クリーム金/白桜)に合わせる。
  var TEMPLATES = {
    acc1: {
      baseW: 360, aspect: 1024 / 1536,
      // ★2026-08-18(2) 月詠みもお手本シート切り出し方式(digitSheet)へ切替(AD研究室ルカ代行発注・
      //   REQ-research-room-43292a14fc「7がへにょへにょ」の月詠み側恒久対策)。長らく保留していた理由は
      //   「Chami提供の旧シート(local/promo-ref/tsukuyomi-digits.png)がRGB焼込=金属ハイライト筋と"0"の
      //   カウンター穴を色で区別できず背景除去できなかった」ため。→ Chamiが背景抜きの正しい透過版
      //   (local/promo-ref/tsukuyomi-digits-rgba.png・2172x724 RGBA)を提供。AD研で実測確認済み
      //   (透明81.1%/不透明8.9%=宵桜と同格・四隅alpha=0・"0"の中央穴alpha=0で左右ストロークalpha=253,249
      //   =カウンター穴が正しく開いている)。→ assets/promo/tsukuyomi-digits.png へ複製し下記digitSheetを
      //   参照。フォント描画(下のink/drawDigits)は端末フォント依存の退避経路として残す(シート未読込/
      //   デコード前のみ使う)。座標はこのシートをPIL実測(下記glyphsコメント)=acc2(1536x1024)と寸法が
      //   違う(2172x724)ため座標は流用せず本シート専用に採寸。

      // ★2026-08-18 Chami提供のお手本(local/promo-ref/tsukuyomi-digits.png=金の数字シート0〜9)へ実合わせ
      //   (AD研究室ルカ代行発注「77の数字が重く角ばる」)。PILで実ピクセルを採色:
      //   核の最明部≈#fffdf5(ほぼ白のハイライト)/最暗部(下1%)≈#e99b23(濃い金アンバー)。
      //   旧(top #fff6d8 / bottom #f0cf8a)は白寄りでなく彩度も低い"ベージュ"止まりで、
      //   金属的な明→暗の階調(ハイライト→アンバー)が原画より弱かった=そのまま質感の差に直結。
      //   縁/輪郭は色よりも「太さ」が主犯(下記contourW/edgeW参照)。ここでは色だけ暖色金へ寄せ、
      //   contourのアルファも.92→.55へ下げ黒すぎる下地を薄める(縁取りでなく"わずかな浮かせ"に留める)。
      ink: { top: '#fffdf5', bottom: '#f0a83e', edge: 'rgba(224,158,52,.9)', glow: 'rgba(255,224,150,.85)', contour: 'rgba(120,68,18,.55)',
             // ★太さの主犯対策: 旧一律 contour=fs*0.075 / edge=fs*0.024 は、Didone体本来の
             //   「縦太・横極細」のコントラストを均一な太い縁取りで塗り潰し、"重く角ばる"の主因だった
             //   (Windows実機Bodoni MTフォールバック描画と添付screenshotの実機ともに同一の団子状"7"を確認=
             //   フォント差ではなくstroke量が主因と切り分け済み)。acc1だけ大幅に薄く=お手本相当の繊細さへ。
             //   acc2は未指定=下のdrawDigitsの既定値(旧仕様のまま)を使うため無変更。
             contourW: 0.020, edgeW: 0.012, glowW: 0.055 },
      // ★2026-08-18(2) お手本シート切り出し(acc2と同方式・上の切替コメント参照)。
      //   シート=assets/promo/tsukuyomi-digits.png(2172x724 RGBA)。glyphs[n]はシート画素サイズに対する比率。
      //   PIL実測(alpha>32でインク列を検出→10桁がすべて非接触に分離。宵桜と違い7/8の谷間分割は不要):
      //     桁ごとのx0..x1(px)= 0:37-225 / 1:299-399 / 2:470-644 / 3:692-862 / 4:903-1094 /
      //                        5:1140-1308 / 6:1351-1528 / 7:1560-1729 / 8:1760-1936 / 9:1972-2147。
      //   cellY/cellHは10桁共通の帯(全桁のtop最小209〜bot最大505px)=全桁が同じ基準線に揃う(桁別にすると
      //   微小な高さ差でガタつく)。y/hはこの帯、x/wは桁ごと。
      digitSheet: {
        src: 'assets/promo/tsukuyomi-digits.png',
        cellY: 0.28867, cellH: 0.41022,
        glyphs: [
          { x: 0.01703, w: 0.08702 }, // 0
          { x: 0.13766, w: 0.04650 }, // 1
          { x: 0.21639, w: 0.08057 }, // 2
          { x: 0.31860, w: 0.07873 }, // 3
          { x: 0.41575, w: 0.08840 }, // 4
          { x: 0.52486, w: 0.07781 }, // 5
          { x: 0.62201, w: 0.08195 }, // 6
          { x: 0.71823, w: 0.07827 }, // 7
          { x: 0.81031, w: 0.08149 }, // 8
          { x: 0.90792, w: 0.08103 }  // 9
        ]
      },
      discount: { src: 'assets/promo/tsukuyomi-discount-base.png',
                  slot: { x: 0.332, y: 0.306, w: 0.342, h: 0.189 } },
      price:    { src: 'assets/promo/tsukuyomi-price-base.png',
                  // ★2026-08-10 札PNG再生成(Chami)= 焼き込み文字 月影に/綴る/¥/作品 を1.3〜1.5倍へ拡大した新素材へ差し替え。
                  //   ¥が大きくなり縦中心が 0.588→0.557 へ上がり、¥の上下に走る飾り罫の間隔も詰まった(新: 罫y0.492/0.618)。
                  // ★2026-08-10(2)「数字を中心に」(Chami)= 円表示は99円以下の二桁円のみ運用(10円セール想定)。数字を
                  //   札の中心線(作品/綴る/飾り罫の中心=x0.508)へ揃え、¥はその左のプレフィックスに。旧はslot中心0.556で
                  //   右へ寄り「¥ …10」と離れて見えた→ slot中心を0.508へ寄せ「¥10」を作品の真上で中央寄せ(x0.408,w0.20=中心0.508)。
                  //   縦は¥中心y≈0.5545、高さ0.103は罫y0.492/0.618に非接触。二桁なら幅は縮まない(PILプレビュー実測=候補A採用)。
                  // ★2026-08-18(3) 数字シート化後に数字を右へ(Chami『月詠みのこのロゴだけ数字をもう少し右に』→『また5%右に』で数値確定。
                  //   msg=1539134808440185044/1539136290300100608・AD研ルカ代行発注)。移動量=フレーム幅の5%を右へ確定。
                  //   slot中心を0.508→0.558(x0.408→0.458・+5%)。y/h/wは据置き。宵桜(acc2)は不変(C-035)。
                  //   ★シート版(digitSheet)描画で合わせている(フォント版との字幅差で狂わないよう順序=①シート化済②ここで右へ)。実機で¥77の座りを確認。
                  slot: { x: 0.458, y: 0.503, w: 0.20, h: 0.103 } }
    },
    acc2: {
      baseW: 620, aspect: 2172 / 724,
      // ★2026-08-10(2) 数字インクをChami提供の数字テンプレ(local/promo-ref/yoizakura-digits.png)へ実合わせ。
      //   Chami「数字のテンプレを参照できたか回答が欲しい。これね」=あのシートが正=真珠白コア＋銅ローズゴールドの縁
      //   ＋桜ピンクの光彩(月詠みの金とは別系統)。前回は焼き込み¥の金へ目分量で寄せたのが誤り(シート未参照)。
      //   contourは札の緋色から数字を持ち上げる濃プラムのまま維持(シートはグレー地なので縁は不要だが緋色上で必要)。
      // ★2026-08-11 実測し直し(Chami「3枚目のテンプレを使ってよ」=まだ金に見える)。PILで3枚目テンプレの
      //   実ピクセルを採色: 真珠コア#fdfef8 / ローズ字面#e0a093 / 銅ローズゴールド縁#ab5148 / 濃緋輪郭#861a18。
      //   前回(#f3b3a6/edge#c87856/glow#ffaa96)は淡い桜＋橙寄りの縁＋暖光でスケール縮小時に金へ寄って見えた。
      //   字面を実測ローズ#e0a093に濃くし縁を銅赤#ab5148へ、暖光を弱め輪郭を紫#4a1e3a→緋赤系#4a1a16へ=金くすみを断つ。
      ink: { top: '#fdfef8', bottom: '#e0a093', edge: 'rgba(171,81,72,.92)', glow: 'rgba(224,160,147,.5)', contour: 'rgba(74,26,22,.94)',
             // ★2026-08-18 acc1と同根の「重く角ばる」対策(AD研究室ルカ代行発注)。色は2026-08-11実測済みで
             //   正しいまま据置き、太さだけacc1と同じ理屈で薄める(旧・下のdrawDigits既定値
             //   contourW0.075/edgeW0.024がDidoneの縦太・横極細コントラストを塗り潰していた=同一の主犯)。
             //   ただし宵桜は緋色の札の上に乗る(acc1のグレー地手本と違い下地が明るく数字が沈みやすい)ため、
             //   contourはacc1(0.020)よりわずかに残して持ち上げを確保。edge/glowはお手本の細い銅の縁・
             //   柔らかい桜光彩に合わせacc1相当まで細める。
             contourW: 0.028, edgeW: 0.013, glowW: 0.058 },
      // ★2026-08-18 Chami依頼「お手本シートの数字を切り出して貼る」方式(AD研究室ルカ代行発注)。
      //   宵桜はChami添付シート(local/attachments/1539030477833506816_1.png)が実測で正真のRGBA
      //   透過(四隅・字間alpha=0を確認済み)なので、上のink/drawDigits(フォント描画)は使わず
      //   このシートから直接グリフを切り出してdrawImageで貼る(=字形がお手本と完全一致・端末フォント非依存)。
      //   glyphs[n]は sheet画像の幅/高さに対する比率。y/hは10桁共通の帯(cellY/cellH)=全桁が同じ
      //   基準線に揃うよう共有(桁ごとに独立させると微妙な高さ差でガタつく)。座標はPIL実測(下記算出根拠は
      //   引き継ぎ/報告に記載)。assets/promo/yoizakura-digits.pngへ複製済み(?v=はtplImgが自動付与)。
      digitSheet: {
        src: 'assets/promo/yoizakura-digits.png',
        cellY: 0.39160, cellH: 0.18848,
        glyphs: [
          { x: 0.01367, w: 0.09375 }, // 0
          { x: 0.11719, w: 0.06510 }, // 1
          { x: 0.20247, w: 0.09701 }, // 2
          { x: 0.30729, w: 0.09245 }, // 3
          { x: 0.40885, w: 0.08984 }, // 4
          { x: 0.51172, w: 0.09180 }, // 5
          { x: 0.60938, w: 0.09701 }, // 6
          { x: 0.71615, w: 0.07812 }, // 7 (「7」「8」がシート上で接していたため谷間x=1219/1536で分割)
          { x: 0.79427, w: 0.09635 }, // 8
          { x: 0.89518, w: 0.09180 }  // 9
        ]
      },
      discount: { src: 'assets/promo/yoizakura-discount-base.png',
                  slot: { x: 0.364, y: 0.260, w: 0.211, h: 0.490 } },
      price:    { src: 'assets/promo/yoizakura-price-base.png',
                  // 2026-08-10 焼き込み文字拡大の新PNGへ差し替え(Chami)。新¥は字面中心0.474・右端0.404・高さ0.283。
                  //   ¥の右〜作品案内(左端0.595)の開いた緋色フィールドへ数字を置く=価格が主役なので¥より気持ち大きく。
                  // ★2026-08-10(2)「10の位置と大きさが適正か」(Chami)= ①縦中心は¥(0.475)へ据置 ②横は空き
                  //   フィールドの中央(x0.407+w0.185で中心≈0.500)へ ③大きさは h0.405→0.46 でライニング数字の字面高≈0.30
                  //   =¥(0.283)よりわずかに大=価格を主役化。二桁なら幅は縮まない(zw=0.185×3bh > "10"幅≈0.45bh)。
                  // ★2026-08-11「数字を真ん中に合わせて」(Chami)= 焼込文字の実測で空き緋色フィールドは
                  //   ¥右端0.414〜作品案内左端0.606=中心0.510。旧x0.407(中心0.4995)は左寄り＆¥に接触。
                  //   x0.418(中心0.510)で空きフィールドの真ん中へ。※割引「99」は中心0.470で実測フィールド中心0.471に既に一致=据置。
                  slot: { x: 0.418, y: 0.245, w: 0.185, h: 0.46 } }
    }
  };
  var _imgCache = {};
  function tplImg(src) {
    if (!src) return null;
    var im = _imgCache[src];
    if (!im) {
      im = new Image();
      // ★onloadだけでなくdecode()完了まで待つ(仕様§4)。complete=trueでも未デコードだと
      //   drawImageが空描画になり、Canvasの数字だけが先に出る不具合の原因になる。
      im.onload = function () {
        var done = function () { im._ready = true; _composite = null; redraw(); }; // 準備完了→合成を作り直して再描画
        if (typeof im.decode === 'function') { im.decode().then(done).catch(done); }
        else { done(); }
      };
      im.onerror = function () { im._failed = true; };
      im.src = _bust(src);
      _imgCache[src] = im;
    }
    return im._failed ? null : im;
  }

  // ChatGPT分析(Chami依頼2026-07-18「セールラベル既定配置・表示設定」)に沿う既定値。
  //   スクショの現配置を参考に、漫画・メインコピー・顔を邪魔せず自然に馴染む初期値。
  // 既定サイズ: 仕様§3「ラベル幅≈13.5%」を"視認幅"で満たす scale0.72 を、実機確認を踏まえ更に-5%(仕様§8)。
  //   0.72×0.95=0.684。視認幅≈12.6%。左の集中線・「里香さん!?」への重なりを軽減。box基準13.5%(scale0.4)は
  //   縦長PNGの透明余白で視認7%=不可読のため視認基準で管理。
  // ★2026-08-05 Chami指示で既定を73%(0.73)へ引き上げ(旧0.684=68%)。UI表示は Math.round(scale*100)=「73%」。
  var DEFAULT_SCALE = 0.73;
  // ★99円以下(二桁円セール=¥価格ラベル)は札を既定の90%サイズで出す(Chami依頼2026-08-11②)。
  //   0.73×0.9=0.657→0.66(UI表記66%)。二桁円の¥札は実額主役で大きく見えるため既定より一段小さく。
  var PRICE99_SCALE = Math.round(DEFAULT_SCALE * 0.9 * 100) / 100;
  var SCALE_MIN = 0.35, SCALE_MAX = 2.5;
  var LABEL_OPACITY = 0.89;   // 既定不透明度(仕様§4・89%。文字が読めるよう下げすぎない)
  // 色の馴染ませ(仕様§6-8): 金光彩/光沢/彩度を弱め、ラベルだけ浮きすぎるのを抑える近似。
  var LABEL_FILTER = 'saturate(0.92) contrast(0.96) brightness(0.98)';
  var scale = DEFAULT_SCALE;  // 大きさ倍率(SCALE_MIN〜SCALE_MAX)
  var fpos = null;    // 手動位置 {x,y}=ラベル左上のフレーム比(0..1)。null=既定(右上)
  var pct = 0;        // 割引率(セール中のみ>0)
  var priceVal = 0;   // 割引後価格(セール中のみ>0)。価格ラベルの数字
  var ltype = 'discount'; // ラベル種類 'discount'(◯%OFF) | 'price'(¥◯)
  var lastCid = '';   // 直近の作品id(begin/notifyの取り違え防止)
  // 表示ON/OFF(Chami依頼2026-07-16)。既定=ON。新規作成のリセット後もONへ戻す(clear参照)。
  // ★これはあくまで「出す気があるか」のスイッチ。セール判定(onSale)とはAND=定価の作品には
  //   チェックが入っていても出さない(Chami明示)。判定は active() に集約する。
  var enabled = true;
  try { var _e = localStorage.getItem('promo_label_enabled'); if (_e === '0') enabled = false; } catch (e) {}
  try { var _t = localStorage.getItem('promo_label_type'); if (_t === 'price') ltype = 'price'; } catch (e) {}
  // ★大きさ(scale)/位置(fpos)はチャンネル別(__acc1/__acc2)に保持する(Chami依頼2026-08-05
  //   「チャンネルそれぞれで前回のタグの大きさ・位置をリセットせず保持・端末共通」)。acc1(baseW360)と
  //   acc2(620)は実寸が1.7倍違い、共通倍率だと片chで合わせた大きさが他chでフレームからはみ出す元凶
  //   だった=チャンネル別に分ける。旧・共通キーの値は両chへ一度だけ複製して引き継ぐ(下のmigrate)。
  //   起動時＋アカウント切替(account-changed)で loadLabelPrefs() が現chの値を読み直す。種別(type)/表示ON
  //   (enabled)は作品・運用に紐づくので従来どおり全ch共通(bluesky.js/stock.js が promo_label_type を読む互換維持)。
  (function migratePromoAcctOnce() {
    try { if (localStorage.getItem('promo_label_acct_split_migrated') === '1') return; } catch (e) { return; }
    ['promo_label_scale', 'promo_label_fpos'].forEach(function (base) {
      var old; try { old = localStorage.getItem(base); } catch (e) { old = null; }
      if (old == null) return;
      ['acc1', 'acc2'].forEach(function (a) {
        try { if (localStorage.getItem(base + '__' + a) == null) localStorage.setItem(base + '__' + a, old); } catch (e) {}
      });
    });
    try { localStorage.setItem('promo_label_acct_split_migrated', '1'); } catch (e) {}
  })();
  function loadLabelPrefs() {
    scale = DEFAULT_SCALE; fpos = null;
    try { var _s = parseFloat(localStorage.getItem(lk('promo_label_scale'))); if (_s >= SCALE_MIN && _s <= SCALE_MAX) scale = _s; } catch (e) {}
    try { var _p = JSON.parse(localStorage.getItem(lk('promo_label_fpos')) || 'null'); if (_p && typeof _p.x === 'number' && typeof _p.y === 'number') fpos = _p; } catch (e) {}
  }
  loadLabelPrefs();
  // ①リロードで割引タグが消える不具合の対策(Chami依頼2026-08-02①)。
  //   pct/priceVal は notify() でしか入らず、リロード直後は作品情報を取り直すまで0=非表示になっていた。
  //   直近の値を永続化して復元し、作品替え(begin)・新規作成(clear)で正しく上書きする。
  try {
    var _v = JSON.parse(localStorage.getItem('promo_label_vals') || 'null');
    if (_v) {
      if (typeof _v.pct === 'number') pct = _v.pct;
      if (typeof _v.priceVal === 'number') priceVal = _v.priceVal;
      if (typeof _v.cid === 'string') lastCid = _v.cid;
    }
  } catch (e) {}

  function acct() { return window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'; }
  // 🏷ラベルの大きさ/位置はチャンネル別キー(base__acc)で保持。(Chami依頼2026-08-05)
  function lk(base) { return base + '__' + acct(); }
  function tplAcct() { return TEMPLATES[acct()] || TEMPLATES.acc1; }
  function tplVariant() { return tplAcct()[ltype] || tplAcct().discount; }
  // 表示する数字。指示書§7: 正の整数のみ(0/負/NaN/undefinedは不正=非表示)。
  function val() {
    var v = ltype === 'price' ? priceVal : pct;
    return (typeof v === 'number' && isFinite(v) && Math.floor(v) === v && v > 0) ? v : 0;
  }
  // 表示可否の唯一の判定点。val()>0 = セール中かつ値が正当(notifyがonSaleの時だけ値を入れる=定価は0)。
  // enabled = Chamiのチェックボックス。両方満たした時だけ描く。
  function active() { return enabled && val() > 0; }
  // フォールバック帯の文言(テンプレ未読込時のみ)。
  function labelText(v) {
    if (ltype === 'price') return (acct() === 'acc2' ? '今宵の¥' + v + '作品案内🌸' : '月影に綴る¥' + v + '作品🌙');
    return acct() === 'acc2' ? ('今だと' + v + '%OFF🌸') : ('今なら' + v + '%OFF🌙');
  }
  // ラベル箱の寸法(フレーム単位)。テンプレPNGが読めていれば実アスペクト、無ければ定義値/帯。
  function boxWH() {
    var t = tplAcct(), v = tplVariant();
    var w = t.baseW * scale;
    var img = tplImg(v.src);
    var asp = (img && img.naturalWidth) ? (img.naturalWidth / img.naturalHeight) : t.aspect;
    return { w: w, h: w / asp };
  }
  function lw() { return boxWH().w; }
  function lh() { return boxWH().h; }

  // 既定位置(右上・フレーム比)。scale込みで右端に余白40px。
  // 既定位置=漫画左上へ軽く重ねる(仕様§2)。左端に密着させず少し内側・メインコピーの下・顔や右のShorts UIを避ける。
  //   852×1280基準の X48/Y300 から、一体感を高めるため 右+10px・下+8px(Chami最終微調整2026-07-18)= X58/Y308。
  function defPos() { return { x: 58 / 852, y: 308 / 1280 }; }
  // 現在のラベル左上(フレーム比)。手動があればそれ。画像外もOK＝端から大きくはみ出す所まで許可(一部は残す)。
  function curPos() {
    var pp = fpos || defPos();
    var minx = (-lw() * 0.7) / FRAME_W, maxx = (FRAME_W - lw() * 0.3) / FRAME_W;
    var miny = (-lh() * 0.7) / FRAME_H, maxy = (FRAME_H - lh() * 0.3) / FRAME_H;
    return { x: Math.min(Math.max(minx, pp.x), maxx), y: Math.min(Math.max(miny, pp.y), maxy) };
  }

  function roundRectPath(ctx, x, y, w, h, r) {
    if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // ── ラベル合成(方式A・仕様§2/§3): テンプレPNG+数字を1枚のオフスクリーンCanvasへ焼く。
  //   これに"だけ"フェードを掛ける=数字が本体と別タイミング/別透明度で出る不具合を根絶(仕様§1/§10)。
  //   キャッシュキー=acct|type|value|src。値/アカウント/種別が変わったら作り直す(_composite=null)。
  var _composite = null, _compKey = '';
  function compositeReady_() {
    var v = tplVariant(), img = tplImg(v.src);
    if (!img || img._failed) return null;                  // PNG恒久失敗=帯フォールバックへ
    if (!(img.complete && img.naturalWidth)) return null;  // 読込前=まだ描かない(仕様§4「読込中は全体非表示」)。
    //   ※decode完了(_ready)時にonloadが_composite=nullで作り直す=万一complete先行で空焼きしても是正される。
    var key = acct() + '|' + ltype + '|' + val() + '|' + v.src;
    if (_composite && _compKey === key) return _composite;
    var off = document.createElement('canvas');
    off.width = img.naturalWidth; off.height = img.naturalHeight;
    var octx = off.getContext('2d');
    octx.clearRect(0, 0, off.width, off.height);
    octx.drawImage(img, 0, 0);                             // 本体+装飾+三日月+固定文言(PNGに焼込済)
    // ★2026-08-18 digitSheet(お手本切り出し)があればそちらを優先。シート画像が未読込/デコード前や
    //   layoutDigitGlyphsが空を返した(数字以外の文字等)場合は、その回だけ従来のフォント描画へ自動退避
    //   (シート読込完了時はtplImgのonloadが_composite=nullで作り直すため、次フレームでシート版に更新される)。
    var tpl = tplAcct(), digitSheet = tpl.digitSheet, usedSheet = false;
    if (digitSheet) {
      var sheetImg = tplImg(digitSheet.src);
      if (sheetImg && !sheetImg._failed && sheetImg.complete && sheetImg.naturalWidth) {
        usedSheet = drawDigitsFromSheet(octx, sheetImg, digitSheet, 0, 0, off.width, off.height, v.slot, String(val()));
      }
    }
    if (!usedSheet) drawDigits(octx, tpl.ink, v.slot, 0, 0, off.width, off.height, String(val())); // 数字も同じ1枚へ
    runPreflight_(octx, off.width, off.height, v.slot, acct(), ltype); // 作成時プリフライト(既定OFF・警告のみ)
    _composite = off; _compKey = key;
    return off;
  }
  function invalidateComposite_() { _composite = null; _compKey = ''; }

  // app.js drawFrame から毎フレーム呼ばれる。フレーム(W×H)にラベルを重ね描き。
  //   reveal(0..1)=前景画像と同じ登場進捗(Chami依頼2026-07-18)。ラベルは"1枚の合成画像"として
  //   前景画像と同じ透明度進行でフェードイン(仕様§5)。子要素の個別アニメ・個別透明度は一切無し。
  function drawOverlay(ctx, W, H, reveal) {
    if (!active()) return;
    var rv = (typeof reveal === 'number') ? Math.max(0, Math.min(1, reveal)) : 1;
    if (rv <= 0) return; // まだ出ていない(前景画像と同じタイミングで登場)
    var sx = W / FRAME_W, sy = H / FRAME_H;
    var cp = curPos();
    var bw = lw() * sx, bh = lh() * sy, x = cp.x * W, y = cp.y * H;
    var v = tplVariant(), img = tplImg(v.src);
    var comp = compositeReady_();
    ctx.save();
    ctx.globalAlpha = rv * LABEL_OPACITY;                  // 合成1枚にだけフェード(前景画像と同一進行)×既定89%
    // ドロップシャドウ=フレームから軽く持ち上がる(仕様§5: 黒0.16・y+3・blur7・濃くしない)。合成のalpha形状に落ちる。
    ctx.shadowColor = 'rgba(0,0,0,0.16)'; ctx.shadowBlur = 7 * sx; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 3 * sy;
    if (comp) {
      // 色の馴染ませ(仕様§6-8): 彩度/コントラスト/明度を少し下げ、金光彩・光沢の浮きを抑える近似(合成全体へ均一)。
      var prevFilter = ctx.filter;
      try { ctx.filter = LABEL_FILTER; } catch (e) {}
      ctx.drawImage(comp, x, y, bw, bh);                   // 本体+数字を1単位で描画=数字だけ先行しない
      try { ctx.filter = prevFilter || 'none'; } catch (e) {}
    } else if (img && img._failed) {
      drawBand(ctx, x, y, bw, bh, sx, sy);                 // PNG恒久失敗時のみ従来の帯(帯も本体+文言が一体)
    }
    // decode未完了(comp==null かつ失敗でもない)は何も描かない=数字だけの先行表示を防ぐ(仕様§4)。
    ctx.restore();
  }

  // 数字だけを slot(数字領域)の中央へ描く。指示書§3.2/§6:
  //   ・slotの中心位置は固定。桁数が変わっても中央揃え(幅に収まるよう縮小のみ)。
  //   ・質感=原画の数字に合わせたグラデ+縁+光彩。フォントは近似セリフ(指示書§12の許容)。
  // ★書体(Chami指摘2026-07-17「数字がクールじゃない」): 原画の数字は Didot/Bodoni 系の
  //   ディドネ体=縦が太く横が極細のハイコントラスト。旧実装は Georgia の bold(700) で、
  //   Georgia は画面可読性重視の低コントラスト書体+太字化で細い横線が潰れる=真逆の性格。
  //   同じ札の「%OFF」(基材に焼き込み済み)が上品なセリフ体のため、数字だけ浮いていた。
  //   → ディドネ体を優先し、太字化をやめる(400)。iOS/macOSは Didot / Bodoni 72 を標準搭載
  //   =主戦場のiPhoneで原画とほぼ一致する。非搭載環境は Georgia の regular へ落ちる。
  var DIGIT_FONT = 'Didot, "Bodoni 72", "Bodoni MT", "Playfair Display", Georgia, "Times New Roman", serif';
  function drawDigits(ctx, ink, slot, x, y, bw, bh, text) {
    var zx = x + slot.x * bw, zy = y + slot.y * bh, zw = slot.w * bw, zh = slot.h * bh;
    var fs = zh;                                   // 高さ基準で開始し、幅に収める
    ctx.save();
    var setF = function () { ctx.font = '400 ' + fs + 'px ' + DIGIT_FONT; };
    setF();
    var pad = zw * 0.04;
    while (fs > zh * 0.4 && ctx.measureText(text).width > zw - pad * 2) { fs -= Math.max(1, fs * 0.04); setF(); }
    var cx = zx + zw / 2, cy = zy + zh / 2;
    ctx.textAlign = 'center';
    // ★数字の縦位置(2026-08-11 Chami「数字だけラベル内の位置が高い」= 色でなく位置。3度目)。
    //   前実装は measureText の actualBoundingBoxAscent/Descent で字面中心を取っていたが、
    //   iOS Safari は下ヒゲの無いライニング数字("10"/"99")でも Descent にフォントのディセンダ量
    //   (≈0.2fs)を算入して返す。すると by=cy+(asc-desc)/2 の desc が水増しされ baseline が上へ→
    //   字が cy より約0.10fs 高く浮く=まさに「位置が高い」の主因だった(PILで基材の焼込文字中心を
    //   実測: 価格0.480/割引0.504=slot中心0.475/0.505とほぼ一致=slotは正しく、浮きは字組み側)。
    //   → 実測字面を捨て、セリフ体ライニング数字の字面高(≈0.66fs)から幾何中心を固定式で置く=端末非依存。
    //   baseline を cy + figH/2 に置くと字面中心が cy に乗る。figH/2≈0.33fs、浮き再発を断つため気持ち下へ(0.34)。
    ctx.textBaseline = 'alphabetic';
    var by = cy + fs * 0.34;
    var grad = ctx.createLinearGradient(0, by - fs / 2, 0, by + fs / 2);
    grad.addColorStop(0, ink.top); grad.addColorStop(1, ink.bottom);
    ctx.lineJoin = 'round'; ctx.miterLimit = 2;
    // 1) 濃い輪郭を「下地」に敷く=明るい札から数字を持ち上げる(かすみ防止)。
    //   数字が明るい札(特に宵桜の桜ピンク)に溶けて霞む主因は「明色の数字＋明色の光彩」で
    //   コントラストが立たなかったこと。下に濃色の縁＋弱い落ち影を敷いてから本体を重ねる。
    var contour = ink.contour || 'rgba(60,30,20,.9)';
    // ★太さは ink.contourW/edgeW/glowW で account別に上書き可能(既定=旧数値のまま=無指定なら無変更)。
    //   2026-08-18 acc1・acc2ともお手本寄せで薄く指定済み(各TEMPLATESのinkコメント参照)。
    //   このフォールバック既定値(0.075/0.024/0.07)は現在どのアカウントからも使われないが、
    //   将来テンプレ追加時の安全側デフォルトとして残す。
    var contourW = (typeof ink.contourW === 'number') ? ink.contourW : 0.075;
    var edgeW = (typeof ink.edgeW === 'number') ? ink.edgeW : 0.024;
    var glowW = (typeof ink.glowW === 'number') ? ink.glowW : 0.07;
    ctx.shadowColor = 'rgba(0,0,0,.30)'; ctx.shadowBlur = fs * 0.05; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = fs * 0.015;
    ctx.lineWidth = Math.max(1.5, fs * contourW); ctx.strokeStyle = contour; ctx.strokeText(text, cx, by);
    ctx.shadowColor = 'transparent';
    // 2) 本体グラデ(くっきり=光彩なしで一度置く)
    ctx.fillStyle = grad; ctx.fillText(text, cx, by);
    // 3) 細い縁で輪郭を締める
    ctx.lineWidth = Math.max(1, fs * edgeW); ctx.strokeStyle = ink.edge; ctx.strokeText(text, cx, by);
    // 4) ごく控えめな光彩(にじませ過ぎない)を最後に本体へ重ねる
    ctx.shadowColor = ink.glow; ctx.shadowBlur = fs * glowW; ctx.shadowOffsetY = 0;
    ctx.fillStyle = grad; ctx.fillText(text, cx, by);
    ctx.shadowColor = 'transparent';
    ctx.restore();
  }

  // ── お手本シート切り出し合成(2026-08-18・Chami依頼): システムフォント(drawDigits)をやめ、
  //   お手本の数字シート(0〜9)から実ピクセルを切り出して貼る。字形がシートと完全一致し端末フォント非依存。
  //   layoutDigitGlyphs は純粋関数(canvas非依存・数値だけ)＝Nodeテスト可。実描画は drawDigitsFromSheet が
  //   その結果を ctx.drawImage で1文字ずつ焼くだけ(副作用はここだけに閉じ込める)。
  //   sheet = { cellY, cellH, glyphs:[{x,w},...] }(すべてシート画像サイズに対する比率・0〜9の10要素)。
  //   natural = { w, h }(シート画像の実画素サイズ)。box = { x, y, w, h }(貼り先の矩形・出力先ピクセル空間)。
  //   text = 数字文字列。gap = 字間(グリフ高さに対する比率・既定0.06)。
  //   戻り値 = [{sx,sy,sw,sh,dx,dy,dw,dh}, ...](drawImageへそのまま渡せる9引数の後半8個)。
  //   text中に0-9以外の文字がある/glyphsに該当が無い場合は空配列を返す(呼び出し側はdrawDigitsへフォールバック)。
  function layoutDigitGlyphs(sheet, natural, box, text, gap) {
    gap = (typeof gap === 'number') ? gap : 0.06;
    var nw = natural.w, nh = natural.h;
    var cellHpx = sheet.cellH * nh;
    var chars = String(text).split('');
    var glyphs = [];
    for (var i = 0; i < chars.length; i++) {
      var idx = chars[i].charCodeAt(0) - 48; // '0'=48
      var g = (idx >= 0 && idx <= 9) ? sheet.glyphs[idx] : null;
      if (!g) return []; // 数字以外/未定義グリフ=呼び出し側でフォールバック
      glyphs.push(g);
    }
    if (!glyphs.length || !cellHpx) return [];
    function totalWidthAt(scale) {
      var tw = 0;
      for (var i = 0; i < glyphs.length; i++) {
        tw += glyphs[i].w * nw * scale;
        if (i < glyphs.length - 1) tw += cellHpx * scale * gap;
      }
      return tw;
    }
    var pad = box.w * 0.04;
    var scale = box.h / cellHpx; // まず高さ基準(slot高さいっぱい)で試す
    var tw = totalWidthAt(scale);
    if (tw > box.w - pad * 2 && tw > 0) scale *= (box.w - pad * 2) / tw; // 幅に収まらなければ縮小
    var drawH = cellHpx * scale;
    tw = totalWidthAt(scale);
    var cx = box.x + box.w / 2, cy = box.y + box.h / 2;
    var curX = cx - tw / 2;
    var topY = cy - drawH / 2;
    var out = [];
    for (var i = 0; i < glyphs.length; i++) {
      var g = glyphs[i];
      var sw = g.w * nw, sh = cellHpx, dw = sw * scale, dh = drawH;
      out.push({ sx: g.x * nw, sy: sheet.cellY * nh, sw: sw, sh: sh, dx: curX, dy: topY, dw: dw, dh: dh });
      curX += dw + cellHpx * scale * gap;
    }
    return out;
  }
  // 実描画(ctx依存)。placementsが空(=layoutDigitGlyphsがフォールバック要求)ならfalseを返し、
  //   呼び出し側(compositeReady_)が従来のdrawDigits(フォント描画)へ切り替える。
  function drawDigitsFromSheet(ctx, sheetImg, sheet, x, y, bw, bh, slot, text) {
    var zx = x + slot.x * bw, zy = y + slot.y * bh, zw = slot.w * bw, zh = slot.h * bh;
    var natural = { w: sheetImg.naturalWidth, h: sheetImg.naturalHeight };
    var placements = layoutDigitGlyphs(sheet, natural, { x: zx, y: zy, w: zw, h: zh }, text);
    if (!placements.length) return false;
    ctx.save();
    for (var i = 0; i < placements.length; i++) {
      var p = placements[i];
      ctx.drawImage(sheetImg, p.sx, p.sy, p.sw, p.sh, p.dx, p.dy, p.dw, p.dh);
    }
    ctx.restore();
    return true;
  }

  // ── プリフライト用の純粋関数(検査専用・描画へは一切使わない・副作用なし) ──
  //   仕様= docs/departments/kaizen-analyst/preflight_digit-on-badge.md
  //   ImageData風の入力 {data:Uint8ClampedArray, width, height} を受け取り、数値だけで完結する
  //   (canvas非依存)。Node からも require() できるよう module.exports/window の両対応で末尾に公開する。

  // sRGB相対輝度(WCAG式・ガンマ展開込み)。r/g/b は 0..255。返り値は 0..1。
  function relLuminance(r, g, b) {
    function ch(c) {
      var s = c / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    }
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
  }
  // WCAGコントラスト比。l1/l2は relLuminance の返り値(どちらが明/暗でも可・順不同で同じ結果)。
  function contrastRatio(l1, l2) {
    var hi = Math.max(l1, l2), lo = Math.min(l1, l2);
    return (hi + 0.05) / (lo + 0.05);
  }
  // 指定region(画像全体に対する比率 x,y,w,h)内で「インク」(=不透明かつ背景と輝度差のある画素)の
  //   最小内包矩形を、画像全体に対する比率 {x,y,w,h} で返す。インクが無ければ null。
  //   opts.alphaMin(既定24/255)= これ未満のalphaは透明として除外。
  //   opts.lumaDiffMin(既定0.12)= 背景輝度とこの差以上ある画素だけをインクとみなす。
  //   opts.bgLuma を渡せばその値を背景輝度として使う。未指定ならregion内の不透明画素の平均輝度で近似
  //   (数字はregionの少数派である前提=既存slot設計と整合)。
  function inkBoxOf(pixels, w, h, region, opts) {
    opts = opts || {};
    region = region || { x: 0, y: 0, w: 1, h: 1 };
    var alphaMin = (typeof opts.alphaMin === 'number') ? opts.alphaMin : 24;
    var lumaDiffMin = (typeof opts.lumaDiffMin === 'number') ? opts.lumaDiffMin : 0.12;
    var rx0 = Math.max(0, Math.round(region.x * w));
    var ry0 = Math.max(0, Math.round(region.y * h));
    var rx1 = Math.min(w, Math.round((region.x + region.w) * w));
    var ry1 = Math.min(h, Math.round((region.y + region.h) * h));
    if (rx1 <= rx0 || ry1 <= ry0) return null;
    var data = pixels.data;
    var bgLuma = opts.bgLuma;
    if (typeof bgLuma !== 'number') {
      var sum = 0, n = 0;
      for (var by = ry0; by < ry1; by++) {
        for (var bx = rx0; bx < rx1; bx++) {
          var bi = (by * w + bx) * 4;
          if (data[bi + 3] < alphaMin) continue;
          sum += relLuminance(data[bi], data[bi + 1], data[bi + 2]);
          n++;
        }
      }
      bgLuma = n > 0 ? sum / n : 0;
    }
    var minX = null, minY = null, maxX = null, maxY = null;
    for (var y = ry0; y < ry1; y++) {
      for (var x = rx0; x < rx1; x++) {
        var idx = (y * w + x) * 4;
        if (data[idx + 3] < alphaMin) continue;
        var luma = relLuminance(data[idx], data[idx + 1], data[idx + 2]);
        if (Math.abs(luma - bgLuma) < lumaDiffMin) continue;
        if (minX === null || x < minX) minX = x;
        if (minY === null || y < minY) minY = y;
        if (maxX === null || x > maxX) maxX = x;
        if (maxY === null || y > maxY) maxY = y;
      }
    }
    if (minX === null) return null;
    return { x: minX / w, y: minY / h, w: (maxX - minX + 1) / w, h: (maxY - minY + 1) / h };
  }
  // インク矩形(画像全体比率)の外周リング(既定6px幅)の平均輝度。インク矩形の内部は含めない。
  //   透明画素(alpha<8)は下地が無い=背景として数えない。リングに有効画素が無ければ null。
  function localBgLuminance(pixels, w, h, inkBoxRel, ringPx) {
    if (!inkBoxRel) return null;
    ringPx = (typeof ringPx === 'number') ? ringPx : 6;
    var data = pixels.data;
    var x0 = Math.round(inkBoxRel.x * w), y0 = Math.round(inkBoxRel.y * h);
    var x1 = Math.round((inkBoxRel.x + inkBoxRel.w) * w), y1 = Math.round((inkBoxRel.y + inkBoxRel.h) * h);
    var ox0 = Math.max(0, x0 - ringPx), oy0 = Math.max(0, y0 - ringPx);
    var ox1 = Math.min(w, x1 + ringPx), oy1 = Math.min(h, y1 + ringPx);
    var sum = 0, n = 0;
    for (var y = oy0; y < oy1; y++) {
      for (var x = ox0; x < ox1; x++) {
        if (x >= x0 && x < x1 && y >= y0 && y < y1) continue; // インク矩形の内部は除外
        var idx = (y * w + x) * 4;
        if (data[idx + 3] < 8) continue;
        sum += relLuminance(data[idx], data[idx + 1], data[idx + 2]);
        n++;
      }
    }
    return n > 0 ? sum / n : null;
  }

  // 作成時プリフライト(仕様§1 P1〜P3相当・警告のみ・fail-open)。
  //   drawDigitsで数字を焼いた直後のオフスクリーンcanvasを読み、(a)実インクboxがslotをはみ出していないか
  //   (b)コントラスト比が閾値以上かをconsole.warnで知らせるだけ。★throw/return/作成停止は絶対にしない
  //   (可用性=喋る側。検査失敗も握りつぶす)。既定OFF=window.GO5_PREFLIGHT か localStorage
  //   'promo_preflight'='1' の時だけ動く(本番の毎回描画では走らせない)。
  var PREFLIGHT_CONTRAST_MIN = 4.5;
  function preflightEnabled_() {
    try { if (typeof window !== 'undefined' && window.GO5_PREFLIGHT) return true; } catch (e) {}
    try { if (typeof localStorage !== 'undefined' && localStorage.getItem('promo_preflight') === '1') return true; } catch (e) {}
    return false;
  }
  function runPreflight_(ctx, cw, ch, slot, accId, type) {
    try {
      if (!preflightEnabled_()) return;
      var img = ctx.getImageData(0, 0, cw, ch);          // 読むだけ=既存描画のピクセルは変えない
      var pixels = { data: img.data, width: cw, height: ch };
      // 探索範囲=slotを一回り広げた領域(はみ出しを検出できるように)。画像端でクランプ。
      var padX = slot.w * 0.5, padY = slot.h * 0.5;
      var rx0 = Math.max(0, slot.x - padX), ry0 = Math.max(0, slot.y - padY);
      var rx1 = Math.min(1, slot.x + slot.w + padX), ry1 = Math.min(1, slot.y + slot.h + padY);
      var region = { x: rx0, y: ry0, w: rx1 - rx0, h: ry1 - ry0 };
      var ink = inkBoxOf(pixels, cw, ch, region);
      if (!ink) { console.warn('[promo-preflight] インク未検出', { acct: accId, type: type, slot: slot }); return; }
      var eps = 1e-6;
      var fits = ink.x >= slot.x - eps && ink.y >= slot.y - eps &&
        (ink.x + ink.w) <= (slot.x + slot.w) + eps && (ink.y + ink.h) <= (slot.y + slot.h) + eps;
      if (!fits) {
        console.warn('[promo-preflight] 実インクboxが宣言slotをはみ出し', { acct: accId, type: type, slot: slot, ink: ink });
      }
      // インク実測輝度=inkBox内のインク画素の平均輝度(1点測りより頑健)。
      var data = pixels.data;
      var ix0 = Math.round(ink.x * cw), iy0 = Math.round(ink.y * ch);
      var ix1 = Math.round((ink.x + ink.w) * cw), iy1 = Math.round((ink.y + ink.h) * ch);
      var sum = 0, n = 0;
      for (var yy = iy0; yy < iy1; yy++) {
        for (var xx = ix0; xx < ix1; xx++) {
          var idx = (yy * cw + xx) * 4;
          if (data[idx + 3] < 24) continue;
          sum += relLuminance(data[idx], data[idx + 1], data[idx + 2]);
          n++;
        }
      }
      var inkLuma = n > 0 ? sum / n : null;
      var bgLuma = localBgLuminance(pixels, cw, ch, ink);
      if (inkLuma != null && bgLuma != null) {
        var ratio = contrastRatio(inkLuma, bgLuma);
        if (ratio < PREFLIGHT_CONTRAST_MIN) {
          console.warn('[promo-preflight] コントラスト比が低い', { acct: accId, type: type, ratio: ratio, threshold: PREFLIGHT_CONTRAST_MIN });
        }
      }
    } catch (e) {
      try { console.warn('[promo-preflight] 検査失敗(無視・fail-open)', e && e.message); } catch (e2) {}
    }
  }

  // 従来の帯(テンプレPNGが読めない間のフォールバック)。
  function drawBand(ctx, x, y, w, h, sx, sy) {
    var r = LBL.radius * scale * Math.min(sx, sy);
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.shadowBlur = 8 * sx; ctx.shadowOffsetY = 2 * sy;
    ctx.beginPath(); roundRectPath(ctx, x, y, w, h, r);
    ctx.fillStyle = 'rgba(224,37,78,.93)'; ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.lineWidth = Math.max(2, 2.5 * sx); ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.stroke();
    var text = labelText(val());
    var fs = LBL.font * scale * sx;
    var setF = function () { ctx.font = '700 ' + fs + 'px "Noto Sans JP", sans-serif'; }; setF();
    while (fs > 20 && ctx.measureText(text).width > w - 18 * sx) { fs -= 1; setF(); }
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fff';
    ctx.fillText(text, x + w / 2, y + h / 2 + fs * 0.04);
    ctx.restore();
  }

  // プレビュー再描画(app.jsのpreview)。連打・ドラッグ中はrAFで間引く。
  var rafPending = false;
  function redraw() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () { rafPending = false; if (window.Go5Preview) window.Go5Preview(); });
  }

  function persist() {
    try { localStorage.setItem(lk('promo_label_scale'), String(scale)); } catch (e) {}       // チャンネル別
    try { localStorage.setItem(lk('promo_label_fpos'), fpos ? JSON.stringify(fpos) : ''); } catch (e) {} // チャンネル別
    try { localStorage.setItem('promo_label_type', ltype); } catch (e) {}                    // 全ch共通(互換)
    // ①リロード耐性：表示値も永続化(cidで作品替え時に古い値を出さない)。
    try { localStorage.setItem('promo_label_vals', JSON.stringify({ pct: pct, priceVal: priceVal, cid: lastCid })); } catch (e) {}
  }
  // FANZA表記に合わせた二段階四捨五入(Chami依頼2026-08-02⑤)。fanza-core.js parseFanzaItem と同じ式。
  //   候補タブ由来の info.discountPct は旧単純丸めのことがあるため、ラベルは価格から取り直して揃える。
  function pctFanza_(listPrice, price) {
    if (!(listPrice > 0) || price == null || price >= listPrice) return 0;
    var raw = (1 - price / listPrice) * 100;
    return Math.round(Math.round(raw * 10) / 10);
  }

  // ---- 位置・大きさの手動調整 ----
  function nudge(dxFrame, dyFrame) {
    if (!active()) return;
    var cp = curPos();
    fpos = { x: cp.x + dxFrame / FRAME_W, y: cp.y + dyFrame / FRAME_H };
    persist(); redraw();
  }
  // リセット(仕様§12): 位置=既定(漫画左上の推奨)・サイズ=既定へ戻す。
  function resetPos() { if (!active()) return; fpos = null; scale = DEFAULT_SCALE; persist(); updateSizeLabel(); redraw(); }
  function updateSizeLabel() {
    var el = document.getElementById('promoSizeVal');
    if (el) el.textContent = Math.round(scale * 100) + '%';
  }
  function setScale(mult) {
    if (!active()) return;
    var ns = Math.min(SCALE_MAX, Math.max(SCALE_MIN, Math.round((scale + mult) * 100) / 100));
    if (ns === scale) return;
    scale = ns; persist(); updateSizeLabel(); redraw();
  }
  // ラベル種類のタップ切替ボタン(Chami依頼2026-08-02⑥)の表示を現在の種別に合わせる。
  function syncTypeBtn() {
    var b = document.getElementById('promoTypeToggle');
    if (!b) return;
    b.textContent = (ltype === 'price') ? '¥価格' : '◯%OFF';
    b.setAttribute('aria-pressed', ltype === 'price' ? 'true' : 'false');
  }
  function updateRow() {
    var row = document.getElementById('promoPosRow');
    if (row) row.hidden = !active();
    updateSizeLabel();
    var sel = document.getElementById('promoType');
    if (sel && sel.value !== ltype) sel.value = ltype;
    syncTypeBtn();
    var pw = document.querySelector('.preview-wrap');
    if (pw) pw.classList.toggle('has-dpad', active());
  }

  // アカウント切替で現チャンネルの大きさ/位置を読み直して再描画。(チャンネル別保持・2026-08-05)
  (function wireAccountChange() {
    var reload = function () { loadLabelPrefs(); updateRow(); redraw(); };
    try {
      if (window.Go5Acct && typeof window.Go5Acct.onChange === 'function') window.Go5Acct.onChange(reload);
      else if (typeof document !== 'undefined') document.addEventListener('account-changed', reload);
    } catch (e) {}
  })();

  // ★以下のwireButtons/wirePointerはdocument前提。Node(require時のプリフライトテスト)で
  //   本ファイルを安全に読み込めるよう呼び出しだけをtypeof documentでガードする(ブラウザは常に
  //   documentがあるため挙動は無変化)。
  function wireButtons() {
    var map = { promoPosL: [-20, 0], promoPosR: [20, 0], promoPosU: [0, -20], promoPosD: [0, 20] };
    Object.keys(map).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', function () { nudge(map[id][0], map[id][1]); });
    });
    var en = document.getElementById('promoEnable');
    if (en) {
      en.checked = enabled;
      en.addEventListener('change', function () {
        enabled = !!en.checked;
        try { localStorage.setItem('promo_label_enabled', enabled ? '1' : '0'); } catch (e) {}
        updateRow(); redraw();
      });
    }
    var sel = document.getElementById('promoType');
    if (sel) {
      sel.value = ltype;
      sel.addEventListener('change', function () {
        ltype = (sel.value === 'price') ? 'price' : 'discount';
        persist(); updateRow(); redraw();
      });
    }
    // ⑥タップ切替ボタン：hidden selectの値を反転→change発火(既存の購読=割引文の単位追従などを効かせる)。
    var tbtn = document.getElementById('promoTypeToggle');
    if (tbtn) {
      tbtn.addEventListener('click', function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        if (!sel) { ltype = (ltype === 'price') ? 'discount' : 'price'; persist(); updateRow(); redraw(); return; }
        sel.value = (sel.value === 'price') ? 'discount' : 'price';
        try { sel.dispatchEvent(new Event('change', { bubbles: true })); } catch (e2) {}
      });
      syncTypeBtn();
    }
    var rs = document.getElementById('promoPosReset'); if (rs) rs.addEventListener('click', resetPos);
    // 大きさは二段階(粗5%・微1%)。Chami依頼2026-07-30。
    var sizeBtns = { promoSizeMinus5: -0.05, promoSizePlus5: 0.05, promoSizeMinus1: -0.01, promoSizePlus1: 0.01 };
    Object.keys(sizeBtns).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', function () { setScale(sizeBtns[id]); });
    });
    updateSizeLabel();
  }
  if (typeof document !== 'undefined') wireButtons();

  // ---- プレビュー上の操作 ----
  // 一本指 = ラベルのドラッグで移動。
  //   ★二本指ピンチ(画像の拡大縮小)は廃止(Chami依頼2026-07-30「二本指ズームは使いにくい」)。
  //     画像の拡大縮小・上下移動はプレビュー横の±ボタン(app.js CONTROLS: imgScale/imgY)で操作する。
  function wirePointer() {
    var cv = document.getElementById('cv');
    if (!cv || !window.PointerEvent) return;
    var drag = null;        // ラベルドラッグ {gx,gy}=掴んだ点とラベル左上のずれ(フレーム比)

    function framePoint(ev) { // ポインタ→フレーム比(0..1)
      var b = cv.getBoundingClientRect();
      if (!b.width || !b.height) return null;
      return { x: (ev.clientX - b.left) / b.width, y: (ev.clientY - b.top) / b.height };
    }

    cv.addEventListener('pointerdown', function (ev) {
      if (!active()) return;                                                                              // ラベル無し=何もしない
      var p = framePoint(ev); if (!p) return;
      var cp = curPos(), wr = lw() / FRAME_W, hr = lh() / FRAME_H;
      if (p.x < cp.x || p.x > cp.x + wr || p.y < cp.y || p.y > cp.y + hr) return;                          // ラベル上のみ掴める
      drag = { gx: p.x - cp.x, gy: p.y - cp.y };
      try { cv.setPointerCapture(ev.pointerId); } catch (e) {}
      ev.preventDefault();
    });
    cv.addEventListener('pointermove', function (ev) {
      if (!drag) return;
      var p = framePoint(ev); if (!p) return;
      fpos = { x: p.x - drag.gx, y: p.y - drag.gy };
      redraw(); // ラベルが指に追従(rAFで間引き)
      ev.preventDefault();
    });
    function endPointer() {
      if (drag) { drag = null; persist(); redraw(); }
    }
    cv.addEventListener('pointerup', endPointer);
    cv.addEventListener('pointercancel', endPointer);
  }
  if (typeof document !== 'undefined') wirePointer();

  // アカウント切替=テンプレ(月詠み⇔宵桜)が変わるため再描画。
  if (typeof document !== 'undefined') document.addEventListener('account-changed', function () { redraw(); });

  if (typeof window !== 'undefined') window.Go5PromoLabel = {
    drawOverlay: drawOverlay,     // app.js drawFrame から呼ぶ(フレームへ重ね描き)
    // 作品情報が確定した時に呼ぶ(bluesky.js renderMovieInfo)。セール中のみ値を保持(定価=0=非表示)。
    notify: function (info) {
      if (!info || !info.title) return;
      // ★セール判定は「実売価<定価」だけで見る(discountPct>0の追加ゲートは外す)。
      //   候補/古いデータでは price・listPrice はあるのに discountPct が0/未設定のことがあり、
      //   その場合ラベルが不当に非表示になっていた(Chami「セールラベルが表示されない・治ってない」)。
      //   実際の割引率は pctFanza_(listPrice,price) で価格から取り直すので discountPct には依存しない。
      var onSale = info.listPrice && info.price != null && info.price < info.listPrice;
      lastCid = String(info.cid || info.title || '');
      pct = onSale ? pctFanza_(info.listPrice, info.price) : 0; // ⑤FANZA表記の丸めで揃える
      priceVal = onSale ? Math.round(info.price) : 0;
      // ★セール価格が99円以下なら自動で「¥価格」表示へ切替(Chami依頼2026-08-11
      //   「セール価格が99円以下なら自動で表示を円表示に。基本そっちをアピールするから」)。
      //   99円以下=二桁円の格安セール=%OFFの数字より実額の安さが刺さる=価格ラベルを主役にする。
      //   価格テンプレも元々「99円以下の二桁円のみ運用」設計(TEMPLATES acc1/acc2 のコメント参照)=整合。
      //   100円以上は従来どおり=既定%OFFと手動切替(promoType/⑥タップ切替)を尊重して触らない。
      if (onSale && priceVal > 0 && priceVal <= 99) {
        ltype = 'price';
        // ★99円以下は札を既定の90%サイズで出す(Chami依頼2026-08-11②)。チャンネル別に手動調整した
        //   大きさ(2026-08-05のチャンネル別保持)は尊重＝既定サイズのままの時だけ自動で90%へ縮める。
        if (scale === DEFAULT_SCALE) scale = PRICE99_SCALE;
      } else if (scale === PRICE99_SCALE) {
        // ★99円以下を離れたら、自動で縮めた90%サイズのままなら既定へ戻す(手で変えていれば尊重)。
        scale = DEFAULT_SCALE;
      }
      persist(); updateRow(); redraw(); // ①値も永続化してリロードで消えないように
    },
    // 別作品の取得開始(前作の値を残さない)。
    begin: function (cid) {
      if (String(cid || '') !== lastCid) { pct = 0; priceVal = 0; persist(); updateRow(); redraw(); }
    },
    // 新規作成の起点(Go5NewMovieReset)。位置は既定へ戻す。
    // ★チェックは必ずONへ戻す(Chami指定2026-07-16「前の情報がリセットされた時もチェックを入れた状態に」)。
    //   前回OFFにしていても、新しい動画では既定のONから始まる=消し忘れでラベルが出ない事故を防ぐ。
    clear: function () {
      pct = 0; priceVal = 0; fpos = null; scale = DEFAULT_SCALE; // 新規動画は既定の位置・サイズから
      enabled = true;
      ltype = 'discount'; // ⑥新規作成のたびに種類は既定の「◯%OFF」へ戻す(Chami依頼2026-08-02「デフォルトは常に%」)
      try { localStorage.setItem('promo_label_enabled', '1'); } catch (e) {}
      var en = document.getElementById('promoEnable'); if (en) en.checked = true;
      var st = document.getElementById('promoType'); if (st) st.value = 'discount';
      persist(); updateRow(); redraw();
    },
    nudge: nudge,
    resetPos: resetPos,
    // 検証用(テストからテンプレ+数字を素のサイズで描かせる。実機能はdrawOverlay経由)。
    _test: {
      slots: TEMPLATES,
      renderTo: function (canvas, acctId, type, value) {
        var t = TEMPLATES[acctId], v = t[type];
        var img = tplImg(v.src);
        if (!img || !img.complete || !img.naturalWidth) return false;
        canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
        var c = canvas.getContext('2d');
        c.clearRect(0, 0, canvas.width, canvas.height);
        c.drawImage(img, 0, 0);
        var used = false;
        if (t.digitSheet) {
          var sheetImg = tplImg(t.digitSheet.src);
          if (sheetImg && sheetImg.complete && sheetImg.naturalWidth) {
            used = drawDigitsFromSheet(c, sheetImg, t.digitSheet, 0, 0, canvas.width, canvas.height, v.slot, String(value));
          }
        }
        if (!used) drawDigits(c, t.ink, v.slot, 0, 0, canvas.width, canvas.height, String(value));
        return true;
      }
    }
  };

  if (typeof document !== 'undefined') updateRow();

  // ── Node向け公開(プリフライトの純粋関数のみ・テスト専用) ──
  //   ブラウザ側は window.Go5PromoLabel(上)経由。ここは tests/test_promo_preflight.js が
  //   require('../js/promo-label.js') する入口。
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      inkBoxOf: inkBoxOf,
      relLuminance: relLuminance,
      contrastRatio: contrastRatio,
      localBgLuminance: localBgLuminance,
      layoutDigitGlyphs: layoutDigitGlyphs,
      TEMPLATES: TEMPLATES   // テスト用(tests/test_promo_digit_sheet.js が実テンプレのdigitSheetを検査)
    };
  }
})();
