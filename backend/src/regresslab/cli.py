"""Run the demo on loopback or verify its local persisted records."""

import argparse
import json
import os
from pathlib import Path

from .main import ROOT, create_app


def main():
    parser = argparse.ArgumentParser(description="RegressLab 本地描述性 Demo")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="启动本地中文工作台与 API")
    demo.add_argument("--port", type=int, default=8080)
    sub.add_parser("doctor", help="校验数据库、历史记录摘要与前端构建")
    args = parser.parse_args()
    if args.command == "demo":
        if not 1 <= args.port <= 65535:
            parser.error("port must be 1—65535")
        import uvicorn
        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, limit_concurrency=8)
    else:
        app = create_app()
        print(json.dumps({
            "mode": "DEMO_DESCRIPTIVE_ONLY", **app.state.store.check(),
            "frontend_built": (ROOT / "frontend/dist/index.html").exists(),
            "data_directory": str(Path(os.environ.get("REGRESSLAB_DATA_DIR", ROOT / "var")).resolve()),
            "gpu_training": "NOT_EXECUTED", "confirmation": "NOT_IMPLEMENTED",
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
