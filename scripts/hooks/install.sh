#!/bin/sh
# 表記チェック pre-commit フックを .git/hooks へ設置する。
# 各マシン/クローンで一度だけ実行: bash scripts/hooks/install.sh
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
cp "$here/pre-commit" "$root/.git/hooks/pre-commit"
chmod +x "$root/.git/hooks/pre-commit"
echo "設置OK: .git/hooks/pre-commit (表記チェック=全角括弧・句点位置)"
