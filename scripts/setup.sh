#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT/backend"
uv sync --frozen --cache-dir ../.cache/uv
cd "$TASK_ROOT/frontend"
npm ci --cache ../.cache/npm
npm run build
echo '准备完成。运行 bash scripts/demo.sh，在浏览器打开 http://127.0.0.1:8080 。'
