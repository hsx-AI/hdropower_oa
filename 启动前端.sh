#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
BUNDLED_RUNTIME="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"

node_is_supported() {
  [ -n "$1" ] && [ -x "$1" ] && "$1" -e '
    const [major, minor] = process.versions.node.split(".").map(Number);
    process.exit(major > 22 || (major === 22 && minor >= 12) ? 0 : 1);
  ' >/dev/null 2>&1
}

PROJECT_NODE="$(command -v node || true)"
if ! node_is_supported "$PROJECT_NODE"; then
  if node_is_supported "$BUNDLED_RUNTIME/node/bin/node"; then
    PROJECT_NODE="$BUNDLED_RUNTIME/node/bin/node"
  else
    echo '未找到兼容的 Node.js。此项目要求 Node.js 22.12+。' >&2
    if [ -n "$PROJECT_NODE" ]; then
      echo "当前系统版本：$("$PROJECT_NODE" --version 2>/dev/null || echo 无法读取)。" >&2
    fi
    echo '请安装兼容版本后重新运行；启动脚本不会修改系统 Node.js。' >&2
    exit 1
  fi
fi

# pnpm 启动 Vite 时会通过 PATH 查找 node，必须同步切换子进程运行时。
export PATH="$(dirname -- "$PROJECT_NODE"):$PATH"
hash -r
echo "使用 Node.js $("$PROJECT_NODE" --version)：$PROJECT_NODE"

if command -v pnpm >/dev/null 2>&1; then
  PROJECT_PNPM="$(command -v pnpm)"
elif [ -x "$BUNDLED_RUNTIME/bin/fallback/pnpm" ]; then
  PROJECT_PNPM="$BUNDLED_RUNTIME/bin/fallback/pnpm"
else
  echo '未找到 pnpm。请先安装 Node.js 22.12+ 和 pnpm。'
  exit 1
fi
if [ ! -d node_modules ]; then
  "$PROJECT_PNPM" install
fi
exec "$PROJECT_PNPM" dev "$@"
