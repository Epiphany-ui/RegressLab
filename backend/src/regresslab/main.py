"""Bounded, loopback-only descriptive demo HTTP interface.

The /api/demo namespace is intentionally separate from the future /api/v1
contract. It never claims to register verified models or consume C evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from . import __version__
from .domain import DomainError, analyze, hash_json, parse_jsonl, validate_dataset, validate_predictions
from .reports import render_html, report_payload
from .storage import Store

ROOT = Path(__file__).resolve().parents[3]
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 31 * 1024 * 1024
logger = logging.getLogger("regresslab")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def failure(code: str, message: str, status: int, details: dict | None = None, request_id: str | None = None):
    return JSONResponse({"error": {
        "code": code, "message": message, "details": details or {}, "request_id": request_id,
    }}, status_code=status)


class LocalRequestGuard:
    """Limit actual incoming bytes and prevent cross-site writes to localhost."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        headers = dict(scope.get("headers", []))
        if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = headers.get(b"origin", b"").decode("latin1")
            host = headers.get(b"host", b"").decode("latin1")
            allowed = {
                f"{scope.get('scheme', 'http')}://{host}",
                "http://127.0.0.1:5173", "http://localhost:5173",
            }
            if origin and origin not in allowed:
                return await failure("ORIGIN_REJECTED", "此本地 Demo 不接受跨站写入。", 403, request_id=request_id)(scope, receive, send)
            if headers.get(b"sec-fetch-site") == b"cross-site":
                return await failure("ORIGIN_REJECTED", "此本地 Demo 不接受跨站写入。", 403, request_id=request_id)(scope, receive, send)
            try:
                declared = int(headers.get(b"content-length", b"0"))
            except ValueError:
                return await failure("INVALID_REQUEST", "Content-Length 无效。", 400, request_id=request_id)(scope, receive, send)
            if declared < 0 or declared > MAX_BODY_BYTES:
                return await failure("UPLOAD_TOO_LARGE", "请求总大小不能超过 31 MiB。", 413, request_id=request_id)(scope, receive, send)
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                size += len(body)
                if size > MAX_BODY_BYTES:
                    return await failure("UPLOAD_TOO_LARGE", "请求总大小不能超过 31 MiB。", 413, request_id=request_id)(scope, receive, send)
                chunks.append(body)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await receive()
        else:
            bounded_receive = receive

        async def response_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ])
            await send(message)
        await self.app(scope, bounded_receive, response_send)


def build_record(texts: dict, metadata: dict, fixture_only: bool = False) -> dict:
    source = {
        "name": metadata["name"], "version": metadata["source_version"],
        "source_url": metadata["source_url"], "license": metadata["license"],
        "fixture_only": fixture_only,
    }
    dataset = validate_dataset(parse_jsonl(texts["dataset"]), source)
    parser = metadata["parser_version"]
    old = validate_predictions(parse_jsonl(texts["old"]), dataset, parser)
    new = validate_predictions(parse_jsonl(texts["new"]), dataset, parser)
    if old["run_id"] == new["run_id"]:
        raise DomainError("RUN_ID_MISMATCH", "旧版和新版必须分别提供独立的运行 ID。")
    result = analyze(dataset, old, new)
    cases = result.pop("discovery_cases")
    raw_hashes = {key: hashlib.sha256(value.encode("utf-8")).hexdigest() for key, value in texts.items()}

    def model(name: str, predictions: dict) -> dict:
        return {
            "name": name, "kind": "DEMO_PREDICTION_IMPORT", "run_id": predictions["run_id"],
            "provenance_status": "DECLARED", "identity_verified": False,
            "weights_sha256": None, "inference_config_sha256": None,
            "prediction_content_sha256": predictions["content_sha256"],
            "parser_version": parser,
        }

    public = {
        **result, "id": str(uuid4()), "name": metadata["name"], "created_at": now(),
        "fixture_only": fixture_only, "status": "SUCCEEDED", "demo_version": __version__,
        "old_model": model(metadata["old_model_name"], old),
        "new_model": model(metadata["new_model_name"], new),
        "dataset": {**dataset["manifest"], "raw_sha256": raw_hashes["dataset"], "source": source},
        "coverage": {"old": old["coverage"], "new": new["coverage"]},
        "scope": old["scope"], "scope_hash": old["scope_hash"], "input_sha256": raw_hashes,
    }
    public["limitations"].extend([
        "合成工程夹具仅验证软件行为，不代表任何真实模型效果。" if fixture_only else "用户导入结果；系统未独立验证推理、权重、训练或运行来源。",
        "本 Demo 未登记完整模型来源与 run_manifest，不支持 TRAINING_UPDATE 或正式实验结论。",
        "未进行 DEV100例×3 稳定性门禁；C/A 不参与统计或分组。",
        "该报告遵循独立 Demo 格式，不是最终 report.schema.json 的成品报告。",
    ])
    public["content_sha256"] = hash_json(public)
    return {
        "public": public, "cases": cases,
        "private": {"input_texts": texts, "dataset": dataset, "old_predictions": old, "new_predictions": new},
    }


def create_app(database_path: Path | None = None, frontend_dist: Path | None = None) -> FastAPI:
    data_dir = Path(os.environ.get("REGRESSLAB_DATA_DIR", ROOT / "var"))
    app = FastAPI(title="RegressLab Demo", version=__version__, docs_url="/api/demo/docs", openapi_url="/api/demo/openapi.json", redoc_url=None)
    app.state.store = Store(database_path or data_dir / "demo.sqlite3")
    app.add_middleware(LocalRequestGuard)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        status = 404 if exc.code == "NOT_FOUND" else 500 if exc.code == "STORAGE_ERROR" else 413 if exc.code == "FILE_TOO_LARGE" else 422
        # Details contain schema fields, counts and IDs, never input text/raw/gold.
        allowed = {"line", "field", "limit", "label_count", "unseen_label_count", "coverage", "missing_ids", "extra_ids", "duplicate_ids", "issues", "sample_id", "sample_ids"}
        details = {key: value for key, value in exc.details.items() if key in allowed}
        return failure(exc.code, exc.message, status, details, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(x) for x in error["loc"]), "type": error["type"]} for error in exc.errors()[:20]]
        return failure("INVALID_REQUEST", "请检查必填字段、文件和参数。", 422, {"fields": fields}, request.state.request_id)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logger.error("request_failed request_id=%s error_type=%s", getattr(request.state, "request_id", "unknown"), type(exc).__name__)
        return failure("INTERNAL_ERROR", "处理失败，请使用请求 ID 排查服务日志。", 500, request_id=getattr(request.state, "request_id", None))

    @app.get("/api/demo/health")
    def health():
        return {"status": "ok", "mode": "demo", "version": __version__, "limits": {"max_rows": 5000, "max_file_bytes": MAX_FILE_BYTES}, "capabilities": ["strict_import", "paired_discovery_metrics", "discovery_slices", "json_html_export", "local_history"]}

    @app.get("/api/demo/analyses")
    def analyses(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100)):
        return app.state.store.summaries(page, page_size)

    @app.get("/api/demo/analyses/{analysis_id}")
    def analysis_detail(analysis_id: UUID):
        return app.state.store.load(str(analysis_id))["public"]

    @app.get("/api/demo/analyses/{analysis_id}/cases")
    def cases(analysis_id: UUID, request: Request, outcome: Literal["all", "negative_flip", "positive_flip", "both_correct", "both_wrong"] = "all", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), role: Literal["DISCOVERY", "CONFIRM", "AUDIT"] = "DISCOVERY"):
        if role != "DISCOVERY" or any(value != "DISCOVERY" for value in request.query_params.getlist("role")):
            return failure("ROLE_FORBIDDEN", "普通案例接口仅开放发现集 D。", 403, request_id=request.state.request_id)
        items = app.state.store.load(str(analysis_id))["cases"]
        if outcome != "all":
            items = [case for case in items if case["outcome"] == outcome]
        return {"items": items[(page - 1) * page_size:page * page_size], "total": len(items), "page": page, "page_size": page_size}

    @app.post("/api/demo/analyses/{analysis_id}/confirm")
    def confirm(analysis_id: UUID, request: Request):
        app.state.store.load(str(analysis_id))
        return failure("EVIDENCE_NOT_CONFIRMABLE", "此 Demo 仅描述发现集，不读取或消耗确认集。", 409, request_id=request.state.request_id)

    @app.get("/api/demo/analyses/{analysis_id}/export")
    def export(analysis_id: UUID, format: Literal["json", "html"] = "json"):
        record = app.state.store.load(str(analysis_id))
        headers = {"Content-Disposition": f'attachment; filename="regresslab-{analysis_id}.{format}"', "Cache-Control": "no-store"}
        if format == "html":
            headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
            return HTMLResponse(render_html(record), headers=headers)
        return Response(json.dumps(report_payload(record), ensure_ascii=False, indent=2, allow_nan=False), media_type="application/json", headers=headers)

    @app.post("/api/demo/fixture", status_code=201)
    def fixture(kind: Literal["basic", "discovery"] = "basic"):
        prefix = "discovery-" if kind == "discovery" else ""
        texts = {key: (ROOT / "examples" / filename).read_text(encoding="utf-8") for key, filename in {
            "dataset": f"{prefix}dataset.jsonl", "old": f"{prefix}old-predictions.jsonl", "new": f"{prefix}new-predictions.jsonl",
        }.items()}
        metadata = {
            "name": "分组发现 · 合成工程夹具" if kind == "discovery" else "成对指标 · 12例工程夹具",
            "source_version": "fixture-v1", "source_url": "local:examples", "license": "Project-owned synthetic engineering fixture",
            "old_model_name": "工程旧版 · 模拟预测", "new_model_name": "工程新版 · 模拟预测", "parser_version": "label-json-v1",
        }
        record = build_record(texts, metadata, fixture_only=True)
        app.state.store.save(record)
        return record["public"]

    async def read_upload(file: UploadFile) -> str:
        data = await file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise DomainError("FILE_TOO_LARGE", "每份文件不能超过 10 MiB。", {"limit": MAX_FILE_BYTES})
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise DomainError("INVALID_ENCODING", "仅接受 UTF-8 JSONL 文件。") from None

    @app.post("/api/demo/analyses", status_code=201)
    async def import_analysis(
        request: Request,
        dataset_file: Annotated[UploadFile, File()],
        old_predictions_file: Annotated[UploadFile, File()],
        new_predictions_file: Annotated[UploadFile, File()],
        name: Annotated[str, Form(min_length=1, max_length=100)],
        old_model_name: Annotated[str, Form(min_length=1, max_length=100)],
        new_model_name: Annotated[str, Form(min_length=1, max_length=100)],
        parser_version: Annotated[Literal["label-json-v1", "label-literal-v1"], Form()] = "label-json-v1",
        source_url: Annotated[str, Form(max_length=2000)] = "未提供",
        source_version: Annotated[str, Form(max_length=100)] = "用户声明",
        license: Annotated[str, Form(max_length=2000)] = "未提供",
    ):
        texts = {}
        try:
            for key, file in [("dataset", dataset_file), ("old", old_predictions_file), ("new", new_predictions_file)]:
                texts[key] = await read_upload(file)
            if not all(value.strip() for value in (name, old_model_name, new_model_name)):
                raise DomainError("INVALID_NAME", "分析名称与版本名称不能为空白。")
            metadata = {"name": name, "old_model_name": old_model_name, "new_model_name": new_model_name, "parser_version": parser_version, "source_url": source_url, "source_version": source_version, "license": license}
            record = await run_in_threadpool(build_record, texts, metadata)
            await run_in_threadpool(app.state.store.save, record)
            return record["public"]
        except DomainError as exc:
            await run_in_threadpool(app.state.store.save_failure, request.state.request_id, now(), exc.code, {key: hashlib.sha256(value.encode("utf-8")).hexdigest() for key, value in texts.items()})
            raise
        finally:
            for file in (dataset_file, old_predictions_file, new_predictions_file):
                await file.close()

    @app.get("/examples/{filename}")
    def example_file(filename: str):
        allowed = {"dataset.jsonl", "old-predictions.jsonl", "new-predictions.jsonl", "discovery-dataset.jsonl", "discovery-old-predictions.jsonl", "discovery-new-predictions.jsonl"}
        if filename not in allowed:
            raise DomainError("NOT_FOUND", "示例文件不存在。")
        return FileResponse(ROOT / "examples" / filename, media_type="application/x-ndjson", filename=filename)

    dist = frontend_dist if frontend_dist is not None else ROOT / "frontend" / "dist"
    if dist.is_dir() and (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse)
        def no_frontend():
            return '<html lang="zh-CN"><meta charset="utf-8"><title>RegressLab</title><p>API 已运行。请在 frontend 执行 npm ci 和 npm run build 后重启。</p><a href="/api/demo/docs">Demo API 文档</a></html>'
    return app
