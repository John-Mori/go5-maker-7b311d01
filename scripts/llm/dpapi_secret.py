#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dpapi_secret.py — Windows DPAPI でローカルの秘密ファイルを暗号化する (O5 / 裁-6 / 2026-07-20).

改善書 P2-3: cli_auth_token.txt / discord_bot_token.txt / deadman_beat_secret.txt などが
local/ 配下に平文で置かれている。単一ユーザー機+gitignore済のためリスクは低いが、
DPAPI(CryptProtectData・ユーザーアカウントに紐づく暗号)で「保存時暗号化」にできる。

設計方針(安全第一):
  ・read_secret(path) は **暗号文でも平文でも透過的に読める**(後方互換)。既存の平文トークンを
    壊さない。移行は任意・段階的。
  ・protect_file(path) で平文→DPAPI暗号(.enc)へ。unprotect は read_secret が自動。
  ・DPAPIはそのWindowsユーザーでしか復号できない=別PC/別ユーザーへ漏れても無意味。
  ・依存ゼロ(ctypesでcrypt32を直叩き)。非Windowsでは平文パススルー(no-op)。

使い方:
  python scripts/llm/dpapi_secret.py --protect local/cli_auth_token.txt   # 暗号化(.encを作り平文を退避)
  python scripts/llm/dpapi_secret.py --selftest                           # 暗号→復号の往復自己診断
  # コード側: from dpapi_secret import read_secret; tok = read_secret("local/cli_auth_token.txt")

★重要(裁-6は「急がない=O5」):本ファイルは**能力の提供**まで。既存の平文トークンを実際に
  暗号化するのは、Chamiが `claude setup-token` で再認証した直後に --protect を1回流すのが安全
  (失効中のトークンを暗号化しても意味がない)。read_secret は平文のままでも動くので、
  移行前後どちらでも既存デーモンは壊れない。
"""
import os
import sys

_ENC_MAGIC = b"DPAPI1\x00"  # 暗号ファイルの先頭マーカー(平文と区別する)


def _win_protect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _win_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def read_secret(path: str) -> str:
    """秘密を読む。暗号ファイル(.enc or マーカー付き)なら復号し、平文ならそのまま返す(後方互換)。"""
    enc = path + ".enc"
    if os.path.exists(enc):
        with open(enc, "rb") as f:
            blob = f.read()
        if blob.startswith(_ENC_MAGIC) and os.name == "nt":
            return _win_unprotect(blob[len(_ENC_MAGIC):]).decode("utf-8", "replace").strip()
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
        if raw.startswith(_ENC_MAGIC) and os.name == "nt":
            return _win_unprotect(raw[len(_ENC_MAGIC):]).decode("utf-8", "replace").strip()
        return raw.decode("utf-8", "replace").strip()
    return ""


def protect_file(path: str) -> str:
    """平文 path を DPAPI暗号化して path+'.enc' に保存、平文は path+'.plain.bak' へ退避。"""
    if os.name != "nt":
        raise SystemExit("DPAPIはWindows専用です(非Windowsは平文運用のまま)")
    with open(path, "rb") as f:
        plain = f.read().strip()
    enc = _ENC_MAGIC + _win_protect(plain)
    with open(path + ".enc", "wb") as f:
        f.write(enc)
    # 平文は消さず .plain.bak へ退避(戻せるように)。運用が安定したら手動削除。
    os.replace(path, path + ".plain.bak")
    return path + ".enc"


def selftest() -> int:
    if os.name != "nt":
        print("非Windows: DPAPI無し=平文パススルーで動作(no-op)")
        return 0
    secret = "hello-スペシャル-秘密-\U0001f511"
    blob = _ENC_MAGIC + _win_protect(secret.encode("utf-8"))
    back = _win_unprotect(blob[len(_ENC_MAGIC):]).decode("utf-8")
    ok = back == secret
    print("DPAPI往復:", "OK" if ok else f"FAIL ({back!r})")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--protect" in sys.argv:
        i = sys.argv.index("--protect")
        p = sys.argv[i + 1]
        out = protect_file(p)
        print(f"暗号化: {out}(平文は {p}.plain.bak へ退避)")
        # 復号確認
        print("復号確認:", "OK" if read_secret(p) else "FAIL")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
