# HTTP API与错误合同

机器权威：[contracts/openapi.json](../contracts/openapi.json)，OpenAPI3.1。本文定义语义；API DTO字段与机器合同一致，不允许额外未声明输入字段。未来实现的`/openapi.json`必须通过合同差异检查。

## 1. 通用约定

基础路径`/api/v1`。除health/ready外，使用`Authorization: Bearer <APP_TOKEN>`；无用户注册接口。所有资源操作先查询归属；资源不存在或跨项目引用返回404，避免泄漏。

JSON响应直接返回资源，不包多层data；列表为`{items,total,page,page_size}`，page从1开始，默认20、最大100。默认按created_at DESC,id ASC，案例按sample_id ASC，slice按rank ASC；不可任意SQL sort。

创建资源返回201；异步提交返回202，body包含resource_id/job_id/status；GET200；校验422；状态冲突409；认证401；上传413；队列/预算429；未知异常500仅显示request_id。X-Request-ID由服务器生成UUID并回传。

```json
{"error":{"code":"SCOPE_MISMATCH","message":"两份预测的评测范围不同","details":{"old_scope":"...","new_scope":"..."},"request_id":"UUID"}}
```

**幂等**：所有POST除文件流上传均要求`Idempotency-Key`（UUID或1—128 ASCII字符）。缺失422。同scope/key不同body409；相同返回原响应。上传使用目标资源状态防重复并要求同键；请求hash为文件原始SHA256+表单元数据hash，读完后确定，不依据客户端声称hash。

## 2. 路由及作用

| 方法/路径（省略前缀） | 语义 |
|---|---|
| GET /health、/ready | 进程存活；DB连接和存储可写（ready失败503）；worker状态单列，不因长训练让存活失败 |
| POST/GET /projects | 创建/分页项目 |
| GET /projects/{project_id} | 项目及计数 |
| POST /projects/{project_id}/archive | 仅归档，无物理删 |
| POST/GET /projects/{project_id}/datasets | multipart导入/分页 |
| GET /datasets/{dataset_id} | 状态、版本manifest、标签表、计数、错误摘要 |
| GET /datasets/{dataset_id}/samples | 仅TRAIN/DEV/DISCOVERY分页；CONFIRM/AUDIT请求403 |
| POST/GET /projects/{project_id}/models | 受限CPU内置训练、已安装OLLAMA检查注册或PRECOMPUTED来源注册/列表 |
| GET /runtime/ollama/models | 分页列服务端白名单内已安装模型/digest；不会pull或安装 |
| POST /projects/{project_id}/models/ollama-check | 检查已安装模型与固定端点兼容性；200检查结果，不创建模型/下载权重 |
| GET /models/{model_id} | 配置、来源、状态与标签hash，不下载模型pickle |
| POST/GET /projects/{project_id}/prediction-sets | 创建scope并入队或等待导入/分页 |
| POST /prediction-sets/{prediction_set_id}/import | 上传预测JSONL；仅PRECOMPUTED且AWAITING_INPUT |
| GET /prediction-sets/{prediction_set_id} | 进度、scope、run_id、hash、覆盖/失败量、run_manifest，无C原文或原始响应 |
| POST/GET /projects/{project_id}/analyses | 创建/分页分析 |
| GET /analyses/{analysis_id} | 配置、阶段、摘要、D/C聚合指标与限制 |
| GET /analyses/{analysis_id}/slices | 候选/确认slice分页 |
| GET /analyses/{analysis_id}/cases | D案例；outcome=negative_flip/positive_flip/both_correct/both_wrong；include_raw=true才返回D原始响应 |
| GET /analyses/{analysis_id}/confusions | D混淆变化分页；old_count/new_count/delta，标签对稳定排序 |
| POST /analyses/{analysis_id}/confirm | 使用冻结家族进行一次确认 |
| POST /analyses/{analysis_id}/resume | 仅恢复失败/取消的DISCOVER或CONFIRM，同配置同候选；不重置C使用权 |
| POST /slices/{slice_id}/review | 设置人工关注/备注，不改统计 |
| GET /analyses/{analysis_id}/report | format=json或html；未完成409；附Content-Disposition |
| POST /analyses/{analysis_id}/suites | 预算B生成套件异步 |
| GET /suites/{suite_id} | 冻结套件元数据/覆盖汇总 |
| GET /projects/{project_id}/suites | 项目套件分页列表 |
| GET /suites/{suite_id}/items | D样本快照分页 |
| GET /suites/{suite_id}/export | 下载suite JSON，自包含合法gold和来源 |
| GET /suites/{suite_id}/inputs | 仅sample_id/text的JSONL，供被测模型输入，不含gold |
| POST /suites/{suite_id}/replays | 指定同任务新模型，异步；PRECOMPUTED先创建SUITE预测集等待上传 |
| GET /replays/{replay_id} | 状态、verdict、逐例失败摘要与对应预测集 |
| GET /suites/{suite_id}/replays | 某套件的历史重放分页列表 |
| GET /jobs/{job_id}、POST /jobs/{job_id}/cancel | 任务/取消 |
| GET /projects/{project_id}/jobs | 项目作业分页 |
| POST /analyses/{analysis_id}/explanations | 旧合同兼容路由，本版始终409 FEATURE_DISABLED |
| GET /explanations/{explanation_id} | 旧资源兼容读取，不产生新说明 |

## 3. 关键请求

### 数据导入

multipart字段：file（canonical JSONL），name，source_name，source_version，source_url，license_url，license_text。通过转换器导入MASSIVE时记录转换器版本；Web只解析canonical格式，避免同一入口猜测多种格式。响应含DatasetVersion ID与导入Job ID。

### 模型训练/注册

```json
{"name":"char-tfidf-v1","kind":"BUILTIN_TFIDF","dataset_version_id":"UUID","config":{"ngram_range":[2,4],"C":1.0,"train_fraction":1.0,"seed":42},"change_type":"REFERENCE","parent_model_version_id":null}
```

PRECOMPUTED同样需dataset_version_id确定labelset，config仍为`{"provider":"user_import","declared_version":"v1","identity_note":"训练来源及推理设置"}`，新增必填change_type、parent_model_version_id和provenance（model-provenance.schema.json）。不接受权重/pickle文件或任意路径；训练日志只作有界文本与声明一致性核对。SERVER_VERIFIED由服务端赋值，外部固定DECLARED。不同source/配置必须新版本；不能更新READY元数据。

OLLAMA请求示例：`{"name":"qwen3-local","kind":"OLLAMA","dataset_version_id":"UUID","change_type":"REFERENCE","parent_model_version_id":null,"config":{"model_tag":"qwen3:0.6b","expected_digest":"64位实际digest","prompt_template":"实际冻结分类提示词","num_ctx":2048,"num_predict":64,"temperature":0,"seed":42,"think":false}}`。这是字段说明而非可原样提交的真实记录。tag仅从服务端安装白名单选择，expected_digest须实时一致；不接收base_url、文件路径、下载地址或自定义代码。register 202以现有AsyncResource响应并排受限PREDICT前检查；短暂Model.TRAINING代表检查而非权重训练。无匹配模型409/INCOMPATIBLE_MODEL。

### 成对比较

```json
{"old_prediction_set_id":"UUID","new_prediction_set_id":"UUID","config":{"max_depth":2,"top_m":20,"min_discovery_support":30,"min_discovery_drop":0.05,"duplicate_jaccard":0.9,"min_confirm_support":40,"min_confirm_drop":0.05,"alpha":0.05,"bootstrap_reps":2000,"seed":42,"feature_catalog_version":"surface-v1"},"evidence_mode":"DESCRIPTIVE_ONLY","stability_report":null}
```

AnalysisCreate新增evidence_mode=CONFIRMATORY或DESCRIPTIVE_ONLY及stability_report（可null）。CONFIRMATORY的LLM比较必须嵌入实际DEV重复报告（stability-report.schema.json），服务器核对100固定ID×3独立run/版本、标签/指纹并存受限artifact。API_SERVICE未知实际外部权重填null，不能虚构hash；其provenance_status仍DECLARED，不允许TRAINING_UPDATE。LOCAL_CHECKPOINT导入有实际权重和训练记录时可以声明TRAINING_UPDATE，仍不成为独立核验。普通分析两份预测须SUCCEEDED且100%合法覆盖。P0生产API中算法值只允许文档默认值；实验配置通过lab命令显式隔离。避免操作者在C确认前后为显著性反复调参。未来开放配置须版本化并记录用途。

### 确认与精选

DESCRIPTIVE_ONLY完成后只给D结果，summary_reason=EVIDENCE_NOT_CONFIRMABLE，C统计null，不消耗C。confirm body只有candidate_set_hash；后端比对冻结值。suites body`{"budget":50,"algorithm":"coverage_diversity_v1"}`。review body`{"flag":"NEEDS_ATTENTION","note":"..."}`。

### 重放

body`{"target_model_version_id":"UUID"}`。API创建Replay与SUITE scope的PredictionSet。BUILTIN/OLLAMA入队预测并判定；PRECOMPUTED返回waiting_input=true、prediction_set_id，用户导入对应输出后worker继续。预测成功发布事务只排一次判定Job（02）。失败/取消则Replay终态ERROR；修正需新建Replay，不重绑旧预测。不得把不完整预测当FAIL来掩盖执行错误。

## 4. 长任务、报告与成本

job进度按resource轮询；完成后resource字段指向最终结果，前端刷新也能恢复。取消返回202并展示cancel_requested，不直接声称停止。报告JSON遵守report.schema.json；HTML必须转义全部用户文本，不引用外部脚本。

预测导入multipart除file和原旁路ID/scope字段，必填application/json编码的run_manifest，字段见prediction-run-manifest.schema.json。每行含run_id、sample_id、prediction_label、raw_response和可选latency_ms。服务器重算所有覆盖/合法性/hash；单行格式正确不代表全scope成功。解析失败仍保留受限原始输入和最多100条错误，不返回C/A内容。LLM每行一次调用，中断需新PredictionSet整轮重跑；不能在看见非法输出后静默重采样。

POST JSON请求默认限制2MiB（训练日志UTF-8最多1MiB），multipart总限制100MiB，流式计量；stability_report600个标签是可控有界对象。报告/历史解释路由的存在不代表P0计划实现生成说明；新建解释始终FEATURE_DISABLED。若未来重新启用，须单独批准功能、预算迁移、外发范围和测试，不能默默开启环境开关。

## 5. 错误码（稳定合同）

INVALID_JSONL、INVALID_SAMPLE、DUPLICATE_ID、CONFLICTING_GOLD、SPLIT_LEAKAGE、UNSEEN_LABEL、INVALID_LABEL、PREDICTION_COVERAGE_ERROR、LABELSET_MISMATCH、SCOPE_MISMATCH、RESOURCE_NOT_READY、INVALID_STATE、CANDIDATE_HASH_MISMATCH、CONFIRMATION_ALREADY_USED、NO_ELIGIBLE_CASES、IDEMPOTENCY_CONFLICT、REQUEST_IN_PROGRESS、QUEUE_FULL、BUDGET_EXCEEDED、TASK_TIMEOUT、WORKER_LEASE_LOST、FEATURE_DISABLED、EXPLANATION_INVALID、STORAGE_ERROR、INTERNAL_ERROR。导入错误细节最多100条，服务器日志用request_id关联。

另有NO_DISCOVERY_SAMPLES、CANCELLED、UNCERTAIN_REMOTE_RESULT。错误码不等于分类标签。

## 6. 新增错误与明确的兼容边界

新增稳定错误码：MODEL_IDENTITY_DRIFT、INCOMPATIBLE_MODEL、PROVENANCE_MISMATCH、INVALID_LINEAGE、RUN_ID_MISMATCH、UNCERTAIN_INFERENCE_RUN、EVIDENCE_NOT_CONFIRMABLE、STABILITY_REPORT_INVALID、EMPTY_SCOPE。缺少稳定性证据的CONFIRMATORY创建返回422/EVIDENCE_NOT_CONFIRMABLE；已为DESCRIPTIVE_ONLY的confirm返回409同code。APP_CONFIG_UPDATE/MODEL_REPLACEMENT本身可以作固定版本比较，但必须按对应含义报告；不得把它们重标真实训练。

BUILTIN可在固定环境下确定性恢复；OLLAMA调用开始后的崩溃不自动重试拼接结果。POST检查接口只连服务端固定Ollama端点，最多检查1个tag，无自动pull/安装。GET库存也仅返回配置白名单，不能探测任意内网地址。43个操作、37条路径；新增ModelProvenance、PredictionRunManifest、StabilityReport等机器对象，独立Schema与OpenAPI同源。


### 原始响应与解析标签一致性

InferenceIdentity必须冻结parser_version：GREEDY_LABEL_TRIE/OLLAMA_JSON_SCHEMA使用label-json-v1，CLASSIFIER_ARGMAX使用label-literal-v1。JSON解析仅接受单对象且只有label键，其值在冻结label_vocab；literal按原始标签精确匹配，不trim猜测映射。raw_response必须非空，服务器按登记解析器重算标签并与prediction_label一致，不一致整批拒绝RAW_LABEL_MISMATCH；raw为实际返回的最终内容，provider思考字段若有单列工件，不拼造最终JSON。JSON Schema只校验形状，方法/解析器对应与动态label须业务验证。
