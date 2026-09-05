"""
5ch台本(cut_list)編集ツール ─ ローカルPythonサーバー(Chami専用・他人に使わせない)。

★設計判断(確定・動かさない)
  土台はローカルの Flask(127.0.0.1 のみ bind・認証なし・デプロイなし)。
  理由=YMMP生成器(cut_list_to_ymmp.py)がローカルのPythonスクリプトで、
  Cloudflare Worker からは呼べないため。旧 worker/(R2バックのCloudflare Worker案)は
  この方針転換により不採用・止血版として残置のみ(このapp.pyとは無関係)。

★正本(絶対に書き換えない・このファイルからはsubprocessで呼ぶだけ)
  - 生成器: cut_list_to_ymmp.py (CUT_LIST_TO_YMMP_PY)
  - 納品前ゲート: validate_ymmp.py (VALIDATE_YMMP_PY)

★編集対象は正本cut_listのみ(D:\\SougouStartFolder\\5chShortMovie\\ 配下)。
  D:\\SougouStartFolder\\5SecMovieMaker\\local\\5ch\\ 配下(退避版・L56のYAML不正エスケープで
  パース不能)は絶対に読み書きしない。走査対象からも除外する。

起動: python 5ch-daihon/server/app.py
"""

from __future__ import annotations

import pathlib
import datetime as _dt
import importlib.util
import json
import shutil
import subprocess
import sys

from flask import Flask, jsonify, request, send_file, send_from_directory
from ruamel.yaml import YAML

# ── 正本・除外パスの定数 ─────────────────────────────────────────
PROJECTS_ROOT = pathlib.Path(r"D:\SougouStartFolder\5chShortMovie")
EXCLUDED_ROOT = pathlib.Path(r"D:\SougouStartFolder\5SecMovieMaker\local\5ch")
ALLOWED_PROJECT_NAME = "holodri_noel"
ALLOWED_CUTLIST_PATH = PROJECTS_ROOT / ALLOWED_PROJECT_NAME / "holodri_noel_cutlist.yaml"

CUT_LIST_TO_YMMP_PY = pathlib.Path(
    r"D:\SougouStartFolder\MangaShortCreateForYMM4\素材・例"
    r"\【YMM4】漫画雑学の型(セリフバージョン)\cut_list_to_ymmp.py"
)
VALIDATE_YMMP_PY = pathlib.Path(
    r"D:\SougouStartFolder\MangaShortCreateForYMM4\YMM4動画作成用Python"
    r"\ymmp_generator\validate_ymmp.py"
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# 生成器 VOICEVOX_STYLE_IDS と同じ集合(2026-09-03確認分)。
# ★生成器側で話者が増減したら、ここも合わせて更新する(単一情報源はあちら)。
VOICE_CHAR_OPTIONS = [
    "四国めたん", "春日部つむぎ", "雨晴はう", "玄野武宏",
    "白上虎太郎", "青山龍星", "剣崎雌雄",
]
VOICE_ROLE_OPTIONS = ["narrator", "viewer"]

# 編集を許可するフィールド(★「編集口をここまでにしろ」の範囲。これ以外は追加しない)。
EDITABLE_TEXT_FIELDS = ("caption_text", "narration_text", "reaction_text", "voice_reading")
EDITABLE_ENUM_FIELDS = ("voice_char", "voice_role")

STATIC_DIR = pathlib.Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")


# ── YAML読み書き(ruamel round_trip・コメント/引用符を保つ) ─────────
def _yaml_rt() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096  # 長い日本語行の折り返しを抑止(意図しない改行挿入を防ぐ)
    return y


def _is_excluded(p: pathlib.Path) -> bool:
    try:
        resolved = p.resolve()
    except OSError:
        return True
    try:
        resolved.relative_to(EXCLUDED_ROOT.resolve())
        return True
    except ValueError:
        return False


def _project_name_from_path(p: pathlib.Path) -> str:
    stem = p.stem  # 例: "holodri_noel_cutlist"
    if stem.endswith("_cutlist"):
        return stem[: -len("_cutlist")]
    return stem


def _find_cutlist_files() -> list[pathlib.Path]:
    """編集対象は holodri_noel の正本1本だけに固定する。"""
    p = ALLOWED_CUTLIST_PATH
    if p.is_file() and not _is_excluded(p):
        return [p]
    return []


def _resolve_project_yaml(name: str) -> pathlib.Path | None:
    if name != ALLOWED_PROJECT_NAME:
        return None
    p = ALLOWED_CUTLIST_PATH
    if p.is_file() and not _is_excluded(p):
        return p
    return None


def _backup_yaml_before_write(yaml_path: pathlib.Path) -> pathlib.Path:
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = yaml_path.with_name(f"{yaml_path.name}.bak_{stamp}_app")
    suffix = 2
    while backup.exists():
        backup = yaml_path.with_name(f"{yaml_path.name}.bak_{stamp}_app_{suffix}")
        suffix += 1
    shutil.copy2(yaml_path, backup)
    return backup


def _assert_ymmp_file_ok(ymmp_path: pathlib.Path) -> None:
    spec = importlib.util.spec_from_file_location("validate_ymmp_gate", VALIDATE_YMMP_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"validate_ymmp.py を読み込めません: {VALIDATE_YMMP_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with ymmp_path.open("r", encoding="utf-8-sig") as f:
        ymmp = json.load(f)
    module.assert_ymmp_ok(ymmp, str(ymmp_path))


def _to_plain(obj):
    """ruamel の CommentedMap/CommentedSeq/スカラー型を素のPython値へ変換する(JSON化用)。"""
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    return str(obj)


# ── /api/projects ────────────────────────────────────────────────
@app.get("/api/projects")
def api_projects():
    projects = []
    for p in _find_cutlist_files():
        projects.append({
            "name": _project_name_from_path(p),
            "path": str(p),
            "folder": p.parent.name,
        })
    return jsonify(ok=True, projects=projects)


# ── /api/project/<name> (GET) ──────────────────────────────────────
@app.get("/api/project/<name>")
def api_get_project(name):
    yaml_path = _resolve_project_yaml(name)
    if yaml_path is None:
        return jsonify(ok=False, error="project_not_found"), 404

    try:
        yaml = _yaml_rt()
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.load(f)
    except Exception as e:  # noqa: BLE001 - 読み込み失敗はそのままエラー表示に回す
        return jsonify(ok=False, error=f"yaml_load_failed: {e}"), 500

    cuts_out = []
    for c in (data.get("cuts") or []):
        cuts_out.append({
            "cut_id": str(c.get("cut_id") or ""),
            "image_file": str(c.get("image_file") or ""),
            "phase": str(c.get("phase") or ""),
            "cut_type": str(c.get("cut_type") or ""),
            "caption_text": str(c.get("caption_text") or ""),
            "narration_text": str(c.get("narration_text") or ""),
            "reaction_text": str(c.get("reaction_text") or ""),
            "voice_reading": str(c.get("voice_reading") or ""),
            "voice_char": str(c.get("voice_char") or ""),
            "voice_role": str(c.get("voice_role") or ""),
        })

    project_dir = yaml_path.parent
    assets_dir = project_dir / "assets"
    images = []
    if assets_dir.exists():
        for p in sorted(assets_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
                images.append(p.relative_to(assets_dir).as_posix())

    return jsonify(
        ok=True,
        name=name,
        yaml_path=str(yaml_path),
        assets_dir=str(assets_dir),
        images=images,
        work=_to_plain(data.get("work") or {}),
        globalParams=_to_plain(data.get("global") or {}),
        voices=_to_plain(data.get("voices") or {}),
        narrator_char=str(data.get("narrator_char") or ""),
        cuts=cuts_out,
        voice_char_options=VOICE_CHAR_OPTIONS,
        voice_role_options=VOICE_ROLE_OPTIONS,
    )


# ── /api/project/<name> (POST・書き戻し) ───────────────────────────
def _resolve_image_value(raw: str, project_dir: pathlib.Path) -> tuple[str | None, str | None]:
    """アセット選択欄の値(相対パス想定)を正本と同じ絶対パス文字列へ直す。
    戻り値 (解決済みパス文字列 or None, エラー文言 or None)。assets配下以外はエラー。
    """
    raw = (raw or "").strip()
    if not raw:
        return "", None
    assets_dir = (project_dir / "assets").resolve()
    candidate = pathlib.Path(raw)
    if not candidate.is_absolute():
        candidate = assets_dir / raw
    try:
        resolved = candidate.resolve()
        resolved.relative_to(assets_dir)
    except (OSError, ValueError):
        return None, f"image_outside_assets: {raw}"
    return str(resolved), None


@app.post("/api/project/<name>")
def api_save_project(name):
    yaml_path = _resolve_project_yaml(name)
    if yaml_path is None:
        return jsonify(ok=False, error="project_not_found"), 404

    body = request.get_json(silent=True) or {}
    edits = body.get("cuts")
    if not isinstance(edits, list) or not edits:
        return jsonify(ok=False, error="missing_cuts_array"), 400

    try:
        yaml = _yaml_rt()
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.load(f)
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=f"yaml_load_failed: {e}"), 500

    cuts_node = data.get("cuts")
    if cuts_node is None:
        return jsonify(ok=False, error="no_cuts_in_document"), 500

    project_dir = yaml_path.parent
    by_id = {}
    for idx, c in enumerate(cuts_node):
        cid = str(c.get("cut_id") or "")
        if cid:
            by_id[cid] = idx

    applied = []
    errors = []
    for edit in edits:
        cut_id = str((edit or {}).get("cut_id") or "")
        if not cut_id:
            errors.append("missing_cut_id")
            continue
        idx = by_id.get(cut_id)
        if idx is None:
            errors.append(f"cut_id_not_found: {cut_id}")
            continue
        node = cuts_node[idx]

        for field in EDITABLE_TEXT_FIELDS:
            if field in edit:
                node[field] = str(edit[field] if edit[field] is not None else "")

        if "voice_char" in edit:
            value = str(edit["voice_char"] or "")
            if value and value not in VOICE_CHAR_OPTIONS:
                errors.append(f"voice_char_not_allowed: {value}")
            else:
                node["voice_char"] = value

        if "voice_role" in edit:
            value = str(edit["voice_role"] or "")
            if value and value not in VOICE_ROLE_OPTIONS:
                errors.append(f"voice_role_not_allowed: {value}")
            else:
                node["voice_role"] = value

        if "image_file" in edit:
            resolved, err = _resolve_image_value(str(edit["image_file"] or ""), project_dir)
            if err:
                errors.append(err)
            else:
                node["image_file"] = resolved

        applied.append(cut_id)

    if errors:
        return jsonify(ok=False, error="validation_failed", details=errors), 400

    try:
        backup_path = _backup_yaml_before_write(yaml_path)
        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=f"yaml_write_failed: {e}"), 500

    return jsonify(ok=True, applied=applied, backup_path=str(backup_path))


# ── /api/image ──────────────────────────────────────────────────
@app.get("/api/image")
def api_image():
    name = request.args.get("project", "")
    file_rel = request.args.get("file", "")
    yaml_path = _resolve_project_yaml(name)
    if yaml_path is None:
        return jsonify(ok=False, error="project_not_found"), 404
    assets_dir = (yaml_path.parent / "assets").resolve()
    try:
        target = (assets_dir / file_rel).resolve()
        target.relative_to(assets_dir)
    except (OSError, ValueError):
        return jsonify(ok=False, error="path_outside_assets"), 400
    if not target.exists() or not target.is_file():
        return jsonify(ok=False, error="not_found"), 404
    return send_file(target)


# ── /api/generate/<name> ────────────────────────────────────────
@app.post("/api/generate/<name>")
def api_generate(name):
    yaml_path = _resolve_project_yaml(name)
    if yaml_path is None:
        return jsonify(ok=False, error="project_not_found"), 404
    if not CUT_LIST_TO_YMMP_PY.exists():
        return jsonify(ok=False, error="generator_script_not_found"), 500

    try:
        gen_proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(CUT_LIST_TO_YMMP_PY), str(yaml_path)],
            cwd=str(CUT_LIST_TO_YMMP_PY.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
    except subprocess.TimeoutExpired as e:
        return jsonify(
            ok=False, error="generator_timeout",
            stdout=e.stdout or "", stderr=e.stderr or "",
        ), 500

    # 生成器と同じロジックで出力先を再解決する(コマンド引数ではなく work.output 基準)。
    out_path = None
    try:
        yaml = _yaml_rt()
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.load(f)
        out_name = (data.get("work") or {}).get("output", "output.ymmp")
        out_path = yaml_path.parent / str(out_name)
    except Exception:
        out_path = None

    result = {
        "ok": gen_proc.returncode == 0,
        "generator": {
            "returncode": gen_proc.returncode,
            "stdout": gen_proc.stdout,
            "stderr": gen_proc.stderr,
        },
        "ymmp_path": str(out_path) if out_path else None,
        "ymmp_exists": bool(out_path and out_path.exists()),
    }

    if out_path and out_path.exists() and VALIDATE_YMMP_PY.exists():
        try:
            _assert_ymmp_file_ok(out_path)
            result["validate"] = {
                "returncode": 0,
                "stdout": f"[OK] assert_ymmp_ok: {out_path}",
                "stderr": "",
                "passed": True,
            }
        except Exception as e:  # noqa: BLE001
            result["validate"] = {
                "returncode": 1,
                "stdout": "",
                "stderr": str(e),
                "passed": False,
            }
            result["ok"] = False
    else:
        result["validate"] = None

    status = 200 if result["ok"] else 500
    return jsonify(result), status


# ── 編集UI(public/を土台に流用) ─────────────────────────────────
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
