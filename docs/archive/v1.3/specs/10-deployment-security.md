# 环境、部署、安全与运行维护

## 1. 部署拓扑与端口

建议容器：web(Node构建+Nginx运行)、api(Python3.11)、worker(同后端镜像不同命令)、db(PostgreSQL16)。对主机默认只暴露`127.0.0.1:8080`；db无公网端口。Nginx将`/api/`代理至api:8000，前端同源。开发端口Vue5173、API8000仅本机。

数据卷：`pgdata`、共享`artifacts`。api/worker以非root用户运行；模型加载目录不是上传目录。时区存UTC，UI格式化为Asia/Shanghai。业务容器无GPU硬依赖；Ollama运行在受信宿主机，独立离线训练环境使用GPU时须另行实测。训练/模型服务不对公网暴露。

## 2. 环境变量合同

| 名称 | 默认/约束 | 用途 |
|---|---|---|
| DATABASE_URL | 必填，postgresql+psycopg://... | DB连接；禁止写进前端 |
| APP_TOKEN | 必填，至少32随机字节的hex或等熵字符串 | 单操作者Bearer认证 |
| ARTIFACT_ROOT | /data/artifacts | 服务端固定根目录 |
| APP_ENV | development/production/test | 调试开关；production禁栈回显 |
| WORKER_CONCURRENCY | 1，P0不可大于1 | CPU任务并发 |
| MAX_CPU_THREADS | 2 | OMP/MKL/OpenBLAS线程上限 |
| JOB_HEARTBEAT_SECONDS | 10 | worker续租 |
| JOB_LEASE_SECONDS | 90 | 租约，必须大于3倍心跳 |
| MAX_JOB_ATTEMPTS | 3 | 崩溃自动恢复上限 |
| MAX_UPLOAD_BYTES | 104857600 | 100MiB |
| MAX_DATASET_ROWS | 50000 | 容量护栏 |
| MAX_TEXT_CODEPOINTS | 8192 | 单行长度 |
| MAX_QUEUED_JOBS | 100 | 入队上限 |
| ENABLE_EXPLANATIONS | false，1.3不可启用 | 旧兼容功能，不列为计划 |
| DEEPSEEK_API_KEY | 未设置；P1分类选做另定 | 仅受信离线/服务端环境，不进前端 |
| DEEPSEEK_MODEL | 实现时核验可用型号并记录返回版本 | 不把2026别名冒充2027固定模型 |
| MAX_EXPLANATION_TOKENS_PER_MONTH | 0 | 历史字段占位，本版不产生解释调用 |
| CLASSIFIER_ENDPOINT_ALLOWLIST | 空 | P1另定合同，本版仅外部预测导入 |
| OLLAMA_BASE_URL | http://127.0.0.1:11434；容器由部署者固定配置宿主地址 | 不接受前端URL/重定向；管理员可配置受信宿主网关 |
| OLLAMA_MODEL_ALLOWLIST | 显式tag集合，无默认任意模型 | 仅允许已安装模型；无pull/create/delete |
| OLLAMA_CONNECT_TIMEOUT_SECONDS | 10 | 连接上限 |
| OLLAMA_READ_TIMEOUT_SECONDS | 120 | 单样本响应上限 |
| MAX_PREDICTION_RUN_SECONDS | 14400 | 整轮推理护栏，非耗时承诺 |
| MAX_JSON_REQUEST_BYTES | 2097152 | 注册/稳定性JSON请求总字节 |
| MAX_TRAINING_LOG_BYTES | 1048576 | 外部来源日志上限，先脱敏 |

`.env.example`只能放占位符；`.env`不进git、不进导出包。真实令牌从密码工具或安全随机生成器取得，不能把本文档示例作默认口令。

## 3. 实现后的启动与验证命令合同

以下命令是开发计划必须实现的入口，现在文档包本身不包含可启动产品。

```text
docker compose build
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose up -d api worker web
docker compose run --rm api python -m regresslab.cli doctor
docker compose run --rm worker python -m regresslab.cli demo --dataset-dir /data/input/massive
```

doctor检查DB迁移、存储原子写、worker心跳、label/config/schema版本、Ollama固定端点/安装白名单/digest与密钥开关；打印诊断，不输出secret。首次下载数据由用户从官方入口获取并保留许可，转换器只接收本地文件。

## 4. 上传与执行边界

- 只收UTF-8 JSONL；Web不收zip/tar/pickle/notebook可执行文件；转换器只读本地已解压JSONL。
- 文件名只用于展示，不参与服务器路径拼接。实际路径由hash生成；禁止`..`、符号链接逃逸与任意file://访问。
- sklearn反序列化仅内部受信产物，hash验证后加载；外部权重不通过Web上传/加载。Ollama只用管理员预装白名单模型；训练LoRA由独立环境离线完成，预测和有界来源manifest导入。拒绝trust_remote_code和任意模型加载器代码。
- 任务文本当数据，不当模板代码/SQL/系统提示。HTML报告全文转义，关闭原始HTML渲染。
- Nginx/API同时限制体积；解析流量按字节计，不信任Content-Length。
- 日志默认不打印完整原文，仅样本ID/hash与错误；明确操作才查看D证据。
- 远程API及生成解释默认禁用，解释本版不可启用。P1若用户自行使用API生成外部预测，须自行知晓会发送哪些评测文本；本地程序不自动外发C/A。API密钥不能进JSONL、训练日志、报告或浏览器。

## 5. 作业与预算

后端默认单作业；CPU作业与Ollama推理串行调度，避免同时占满6GB。每个任务可配置固定硬超时（05）；无上限等待不是恢复策略。取消在批次边界生效；原生训练调用不能即时停止时显示“正在取消”。

P1API用量按请求记录provider/model/request_hash/token实际值或保守预留值。预算扣减用DB事务，不由前端余额决定。服务端密钥只在worker运行时读取。P1不允许智能体自主安装包、执行shell、改统计代码或访问整个文件系统。

## 6. 备份、恢复、监测

备份：停止接受新作业，等待/取消正在发布的任务；记录snapshot_id；`pg_dump`与共享卷一并快照，生成hash清单；恢复到新数据库/新卷后doctor验证引用和schema版本。不能只复制数据库，也不能在线复制一半模型后声称完整备份。

监测：health、ready、worker_last_seen、排队数、失败作业数、存储剩余空间；任一artifact hash不符禁止加载并返回STORAGE_ERROR。日志JSON包含time/request_id/job_id/resource_id/attempt_no/event/error_code，敏感字段固定脱敏。

故障运行手册见13。公网多人部署、TLS终止、用户隔离、恶意模型沙箱和完整审计合规超出P0，需要重新安全评审；不要把本地令牌模式宣传成生产SaaS安全方案。

## 7. LLM调用、漂移与原始输出

Ollama可能没有认证，本地服务只绑定回环/受控宿主网络，不公开11434，不允许浏览器直接调用。API/worker只能访问配置固定的主机端点及固定/tags、/show、/api/chat路径；关闭重定向、外部代理继承、自动pull和动态URL。白名单tag还须核对digest，不以名称代替权重身份。结构化schema只约束JSON形状，不授权模型生成代码/文件路径。

原始输出、训练日志、稳定性报告可能含文本/个人数据，按受限artifact存储；日志先脱敏，普通HTTP不提供任意artifact下载。D证据include_raw显式展开；C/A即使执行失败也不回显原文/响应，只返回计数、错误码和hash。HTML/JSON展示全部转义。raw响应超限整体FAILED/INVALID_LABEL或相应格式错误，原始流最多保留配置上限并标truncated，不得伪称完整。

LLM每行最多一次生成；不按答案质量重试。租约中断产生UNCERTAIN_INFERENCE_RUN，新PredictionSet整轮重新执行；旧文件保留失败证据。只有完整合法scope可进入普通分析，错误率/覆盖作为执行质量单独展示。外部manifest一致性、stable DEV和temperature=0均不能证明实际weights或推理完全确定。
