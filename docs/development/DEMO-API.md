# 描述性 Demo API

本接口是前期有界切片，前缀 `/api/demo`。最终产品 `/api/v1` 的模型来源、run_manifest、异步状态、认证及报告合同仍以[1.3设计基线](../specs/README.md)和[机器合同](../contracts/README.md)为准，不能将此 Demo 的简化输入导入正式实验。服务默认只绑定回环地址。

| 方法 / 路径 | 行为 |
|---|---|
| `GET /health` | Demo 版本、能力和容量限制 |
| `GET /analyses?page=1&page_size=100` | 历史分析摘要，最多每页100条 |
| `POST /fixture?kind=basic` | 用合成12例夹具执行真实校验与计算 |
| `POST /fixture?kind=discovery` | 用大夹具执行固定门槛的分组发现 |
| `POST /analyses` | multipart 导入数据和两份完整预测 |
| `GET /analyses/{id}` | D指标、候选、来源声明、配置和hash |
| `GET /analyses/{id}/cases` | D逐例证据，支持成对结果筛选和分页 |
| `GET /analyses/{id}/export?format=json` | 下载独立Demo JSON报告 |
| `GET /analyses/{id}/export?format=html` | 下载纯静态、转义的HTML报告 |
| `POST /analyses/{id}/confirm` | 固定409，不读取或消耗C |
| `GET /docs`、`GET /openapi.json` | 运行时自动生成的Demo接口文档 |

示例文件由独立的 `/examples/{filename}` 白名单路由提供，仅允许6个合成JSONL文件，不接受客户端路径。

multipart 字段：`name`、`old_model_name`、`new_model_name`（1—100字符）；`parser_version`（`label-json-v1`或`label-literal-v1`，默认前者）；`source_url`（最多2000字符）、`source_version`（最多100）、`license`（最多2000）；三个文件 `dataset_file`、`old_predictions_file`、`new_predictions_file`。来源仅保存为文本，服务器不访问来源URL。

数据使用原[InputSample合同](../contracts/input-sample.schema.json)字段，不能传role。标签表由TRAIN冻结；D/C/A按组件hash决定。预测必须完整覆盖D+C，无gold字段，每行包含 sample_id、prediction_label、run_id、raw_response，可选非负有限 latency_ms。每份只有一个run_id，旧新run须不同。严格重解析raw并比较标签。此步骤验证运行声明的内部一致性，不能独立证明真实单次推理。

案例参数：`outcome=all|negative_flip|positive_flip|both_correct|both_wrong`、`page≥1`、`1≤page_size≤100`。`role=CONFIRM|AUDIT` 返回403；默认只返回DISCOVERY。报表、案例和分析详情均不返回私有输入或C/A原文及原始响应。

成功导入/夹具返回201，列表/详情/导出200，非法输入422，上传超限413，确认409，未知分析404。错误结构为 `{error:{code,message,details,request_id}}`，不回显非法输入的原文。每份文件最多10MiB，请求实际总字节最多31MiB；不只检查Content-Length。

JSON报告包含 `report_schema=regresslab-demo-report-v1`、`analysis` 和 `discovery_cases`。完整产品[报告Schema](../contracts/report.schema.json)尚未适用，避免把缺少权重与推理来源的Demo记录伪装成正式证据。成功记录和原始输入保存在本地SQLite私有payload，公开报告不含private字段。
