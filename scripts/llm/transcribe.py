#!/usr/bin/env python3
"""音声ファイルの文字起こし(faster-whisper small・日本語・CPU)。

使い方: python scripts/llm/transcribe.py <音声ファイル>
モジュール利用: from transcribe import transcribe; text = transcribe(path)
初回はモデル(約460MB)を自動ダウンロード。モデルはプロセス内でキャッシュされる。
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_model = None


def transcribe(path, language="ja"):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _info = _model.transcribe(path, language=language, vad_filter=True)
    return "".join(s.text for s in segs).strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: transcribe.py <音声ファイル>")
        sys.exit(1)
    print(transcribe(sys.argv[1]))
