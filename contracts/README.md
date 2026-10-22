# 机器合同与夹具

- `openapi.json`：HTTP形状基线；服务前缀/api/v1，Bearer认证，POST幂等键。
- `schema.sql`：PostgreSQL16初始结构；实现时转为Alembic0001，不能与迁移重复执行。
- `input-sample.schema.json`：canonical JSONL每一行，不是整个文件数组。
- `prediction-row.schema.json`：预测JSONL每行，每行必须sample_id/prediction_label/run_id/raw_response，耗时可选；raw受限存储。
- `report.schema.json`：完整分析导出；不是lab批比较文件。
- `suite.schema.json`：完整不可变suite导出。
- `default-analysis-config.json`：生产协议常量，实验配置不能悄悄覆盖。
- `examples/`：合法合同示例，不是真实模型或数据来源。示例UUID/hash均为占位；report是合成12行的可手算结果。单行InputSample不是可完整训练的数据集。
- `fixtures/`：纯函数工程测试金标准；不输入真实论文效果表。

OpenAPI3.1和独立Schema采用JSON Schema2020-12语义。独立Schema包含完整$defs，便于离线校验；动态label_vocab、ID全集、跨项目归属、计数守恒与冻结性还必须由业务服务测试，JSON Schema不能代替这些约束。

本包只做静态结构、引用、示例与算术检查。未来实现须在真实PostgreSQL执行迁移，并以正式OpenAPI/JSON Schema验证器与服务端生成规范对照，不能把本文档验证报告当产品验收记录。

1.1新增`selection-experiment-design.json`：lab方法登记与调整规程的机器清单，不是生产API请求或实测run。实际registration仍须填写真实数据/模型/配置hash并通过边界检查。新增`fixtures/selection-baselines.json`为工程选择算例。1.1时的41个操作/17张表属于历史计数。

1.3合同：新增OLLAMA kind与两个受限本机检查接口，43个HTTP操作、37条路径，17张表；实际Schema数以openapi.json为准。Report/SuiteExport schema_version升为1.1，原1.0导出不能直接作为1.1输入。新增model-provenance.schema.json、prediction-run-manifest.schema.json、stability-report.schema.json；TRAINING_UPDATE/应用更新来源、实际权重与推理指纹、完整合法覆盖、单次run和DECLARED来源限制均为业务门禁。stability_report嵌入AnalysisCreate，服务端保存受限产物；stable DEV不是实际权重认证或因果证明。

examples/report.json继续为明确fixture=true的纯工程例子，DESCRIPTIVE_ONLY、C=null、不含虚构真实训练或稳定性结果。examples/analysis-request.json为仅描述形状示例，不能绕过实际预测完整性检查。evaluation_data_sha256排除数据UUID/来源元数据，ConfirmationUse按实际evaluation指纹防重复确认。未运行实际模型/迁移/产品端到端测试。
