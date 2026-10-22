#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"
if [[ ! -x backend/.venv/bin/python || ! -f frontend/dist/index.html ]]; then
  echo '请先执行 bash scripts/setup.sh 安装并构建 Demo。'
  exit 1
fi
exec backend/.venv/bin/python -m regresslab.cli demo --port "${REGRESSLAB_PORT:-8080}"
