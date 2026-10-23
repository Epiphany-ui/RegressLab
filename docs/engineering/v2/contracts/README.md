# v2 研究工件合同草案

本目录仅有工程 **DRAFT** [research-artifacts.schema.json](research-artifacts.schema.json)，不是已经实现的 v2 API、实验输出或学术效果证据。研究来源保持在[不可变源目录](../../../research/v2/source/README.md)，字段语义、内容hash payload、稳定source_i、访问限制及SQLite概念映射见[03领域数据合同](../03-domain-data-contracts.md)。

采用 JSON Schema 2020-12，所有 `$ref` 为文内 `#/$defs/...`，无远程加载依赖。顶层 oneOf 由 artifact_kind 区分：

| $defs定义 | artifact_kind | 计划位置（相对study根） |
|---|---|---|
| StudyRegistration | STUDY_REGISTRATION | registration.json |
| DatasetManifest | DATASET_MANIFEST | dataset/dataset-manifest.json |
| ModelChain | MODEL_CHAIN | chains/<chain_id>/chain-manifest.json |
| PredictionRun | PREDICTION_RUN | 受审计的历史run目录；目标run置selector根外 |
| HistoryView | HISTORY_VIEW | history/<chain_id>/history-view.json |
| PoolManifest | POOL_MANIFEST | pools/<chain_id>/pool-manifest.json |
| MethodRegistration | METHOD_REGISTRATION | methods/<method_id>/method-manifest.json |
| SuiteFreeze | SUITE_FREEZE | suites/<cell_id>/suite-manifest.json |
| FreezeMatrix | FREEZE_MATRIX | freeze/matrix-freeze.json |
| EvaluationResult | EVALUATION_RESULT | evaluations/<evaluation_id>/evaluation-result.json |
| CostLedger | COST_EVENT | costs/cost-ledger.jsonl，每行一个对象 |

未来可用正式 `jsonschema` 验证器检查整个顶层工件；DatasetRow/PredictionRow 则逐JSONL行使用对应命名定义校验，解析器先拒绝重复键与非有限数。启用 format checker 验证 UUID/date-time。这里不附占位hash、训练日志或编造结果；将来合成夹具必须 fixture=true，不能补足真实更新验证。

HistoryView additionalProperties=false，slot仅f0/f1/f2，role仅D或DEV_SELECTOR；没有f3字段或目标路径。MethodRegistration将目标白盒/探测/全池访问与历史标签、参考分数分层。Formal StudyRegistration要求protocol FROZEN、实际来源和完整矩阵、全部决策已批准；FreezeMatrix还需业务层核对注册的全集，不能只验证本地现有文件。

登记/冻结/评价使用同一`comparison_scope`：`CORE_PRE_TARGET`不含全池目标单元，首次完整目标解封只在主矩阵冻结后；`ENHANCED_TARGET_ACCESS`必须引用`parent_core_freeze_sha256`，先冻结增强登记、取得必要全池输入，再冻结增强套件/计分。声明的白盒/有限探测与未声明目标泄漏分开。Schema形状与03/D15的时序条件同时适用；跨事件时序必须由运行校验器证明。

schema不能验证外部内容hash、时间顺序、数组间一一对应、ID完整覆盖、概率向量长度/标签顺序/和、风险公式、套件P成员、预算共享前缀、成本去重或代码访问诚实性；这些必须由独立业务校验与隔离测试执行。artifact原文、target rows和sealed handles不得作为只读工作台公开下载入口。

ArtifactRef分开保存实际文件字节`file_sha256`与该工件语义payload的`content_sha256`，不能用一个摘要混指两种负载。Schema仅检查64位字符串形状；本轮`check-docs.py`的内存见证明确为synthetic，不包含真实训练产物或正式运行。

ViewBundle及事件JSONL的完整机器shape尚未在本目录定义；其发布/状态语义见[04流程成本](../04-workflow-and-costs.md)和[05迁移](../05-demo-migration.md)。计划离线入口为 `python -m regresslab_lab.cli`，本轮不创建该包或命令。
