# 模型升级诊断工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现面向大模型分类应用的退化诊断与回归测试完整系统，以真实小模型微调版本为主验证、LR重新训练为对照。

**Architecture:** 模块化单体，FastAPI控制API与单独worker共享领域代码。PostgreSQL持久任务和结构化数据，共享卷保存内容寻址产物。纯统计算法与DB/网络解耦。

**Tech Stack:** Python3.11、FastAPI/Pydantic2、SQLAlchemy2/Alembic、PostgreSQL16、sklearn/SciPy、Vue3/TypeScript、Node24、pytest/Vitest/Playwright。

**Spec:** 本目录的PRODUCT、00—11、13—19及[机器合同](../contracts/README.md)；版本生成精确配方见19，机器字段以OpenAPI为准。

## Global Constraints

- P0只做有金标准的单标签文本分类/意图识别。
- PostgreSQL16，一个Worker；CPU分析最多2线程；Web主流程不需API密钥，主语言模型微调须先通过6GB资源预实验。
- 单版本≤50,000行，单文本≤8,192 Unicode码点，文件≤100MiB，标签2—200类。
- 训练只用TRAIN，调参只用DEV，D发现、C一次确认、A最终实验。
- 模型输入仅sample_id与text；预测缺/重/多ID或非法标签不可进入能力指标。
- Analysis生产默认参数与[默认分析配置](../contracts/default-analysis-config.json)逐字一致。
- UI不得将NOT_CONFIRMED或Replay PASS写成安全/非劣认证。
- 同一确认家族不在C增删条件；同一模型应用身份对同evaluation_data_sha256只消费一次C，换dataset UUID/来源元数据不能重置。
- worker心跳10秒，租约90秒，最多3次attempt，旧attempt不得发布。
- 所有完成数据、模型、suite和report均有来源/版本/hash；不覆盖历史。

## Review Focus

1. 平行译文/相同文本通过不同ID进入不同角色：M02用transitive component测试固定。
2. 预测失败或标签映射错造成“假退化”：M04/M08严格ID与label验证，ERROR与FAIL分开。
3. 找到组之后在C调阈值或重复确认：M06事务唯一键和角色边界测试。
4. 文件已写但DB未提交、旧worker迟到写结果：M01/M10发布fence与恢复测试。
5. 把首次全量发现成本隐藏成“精选节省费用”：M11成本分项与未来版本盲测报告。

## 文件结构

```text
regresslab/
  docs/contracts/              # 机器合同的版本化基线（现有目录）
  backend/
    pyproject.toml
    uv.lock
    alembic/versions/0001_initial.py
    src/regresslab/
      main.py                  # FastAPI装配，不放业务算法
      config.py
      cli.py                   # doctor/convert-massive/demo/lab入口
      domain/{types,states,hashing,errors}.py
      api/{auth,errors,projects,datasets,models,predictions,analyses,suites,jobs}.py
      data/{canonical,massive,split,features}.py
      models/{builtin,adapters,persistence,ollama,provenance,stability}.py
      analysis/{metrics,discovery,confirmation,reports}.py
      suites/{selection,replay,export}.py
      jobs/{queue,worker,lease,handlers}.py
      storage/{database,orm,repository,artifacts}.py
      explanation/{service,provider,validation}.py
      lab/{runner,baselines,strategies,evaluation,preregistration,change_log}.py
    tests/{unit,integration,contract}/
  frontend/
    package.json
    package-lock.json
    src/{api,router,stores,views,components}/
    tests/
  experiments/                 # 独立锁定的Transformers/PEFT准备环境
    pyproject.toml
    src/regresslab_experiments/{train_lora,infer,manifest,cli}.py
    tests/
  e2e/
  deploy/{Dockerfile.backend,Dockerfile.web,nginx.conf}
  compose.yaml
  .env.example
  docs/                       # 本包与实际验证记录
```

## 共同类型（M01定义，后续不得各自重造）

Pydantic/API类型直接映射OpenAPI；领域算法类型额外定义：

- TextInput：sample_id,text；Prediction：sample_id,prediction_label,latency_ms可空。
- PairedPrediction：sample_id,gold_label,old_prediction_label,new_prediction_label。
- DiscoveryRow：PairedPrediction + text,component_key,features,role固定DISCOVERY。
- ConfirmationRow：PairedPrediction + component_key,features,role固定CONFIRM。
- Candidate：rank,predicate,predicate_hash,discovery；CandidateSet：有序candidates,candidate_set_hash。
- SliceResult：Candidate + confirmation,status；持久化时再分配UUID id。
- SelectionConfig：budget,seed=42,pool_cap=5000；SuiteSelection：items,obligations,coverage,pool_truncated。
- AnalysisConfig包含04全部生产参数；DiscoveryConfig/ConfirmConfig是其只读子投影。

这些类型不得隐含读取数据库。PairedMetrics字段见OpenAPI；错误抛DomainError(code,details)。

## M01：可认证的项目与持久任务基础

**Files:** 创建config.py/main.py/domain、storage/database.py/orm.py、api/auth.py/projects.py、jobs/queue.py/lease.py、迁移、compose与锁文件。

**Interfaces:** `create_project(name: str, description: str) -> Project`；`enqueue_job(project_id: UUID, kind: JobKind, resource_type: str, resource_id: UUID, payload: dict) -> Job`；`claim_job(worker_id: str) -> JobClaim | None`；`publish(claim: JobClaim, update: ResourceUpdate) -> bool`。

- [ ] 写TC-01/29及`test_expired_attempt_cannot_publish`；断言跨项目404、幂等不同body409、过期attempt发布false。
- [ ] `cd backend && uv run pytest tests/integration/test_projects.py tests/integration/test_job_lease.py -q`：先因功能未实现失败。
- [ ] 实现认证、项目、表迁移、短事务队列、attempt_token；提交任务与业务资源同事务。
- [ ] 重跑通过；`alembic upgrade head`空库成功；doctor至少能报告DB/存储状态；记录实际锁文件hash。
- [ ] 提交该可用切片；后续任务使用上述队列，不另加内存队列。

## M02：数据导入与分区封存

**Files:** data/canonical.py,massive.py,split.py,features.py；api/datasets.py；jobs/handlers.py的IMPORT_DATA；tests/unit/test_split.py、integration/test_dataset_import.py。

**Interfaces:** `convert_massive(paths: list[Path], output: Path) -> ConversionManifest`；`validate_and_partition(rows: Iterable[InputSample]) -> ValidatedDataset`；`surface_features(text: str, locale: str) -> dict[str,str|bool]`。

- [ ] 写TC-02/03/04/31；断言同group或传递同文本组件同role、跨官方分区拒绝、未知gold拒绝。
- [ ] `uv run pytest tests/unit/test_split.py tests/integration/test_dataset_import.py -q`先红。
- [ ] 按03实现流式校验、union-find、固定hash分区与manifest，READY内容不可改。
- [ ] 测试绿；真实zh-CN转换后保存实际counts与许可，不硬编码19,521。
- [ ] 提交；接口返回DataVersion ID和持久Job。

## M03：受限CPU模型训练与版本

**Files:** models/builtin.py,persistence.py、api/models.py、TRAIN_MODEL handler、tests/unit/test_training_boundary.py。

**Interfaces:** `train_builtin(dataset: TrainingDataset, config: BuiltinConfig, output_dir: Path) -> ModelArtifact`；`load_internal_model(artifact: ArtifactRef) -> BuiltinClassifier`。

- [ ] 写TC-05：只在C出现的词不进入词表，上传外部pickle没有路由；训练配置不在allowlist时422。
- [ ] `uv run pytest tests/unit/test_training_boundary.py tests/integration/test_models.py -q`先红。
- [ ] 实现03固定Pipeline、TRAIN子集与内容指纹；PRECOMPUTED登记真实微调来源、父版本、权重/推理/来源指纹，来源保持DECLARED；Ollama按固定服务清单登记，不能任意上传执行模型。
- [ ] 测试绿；训练两个固定预设版本并保存真实hash/耗时；不保证新模型分数更高。
- [ ] 提交。


## M03T：真实更新版本准备与资源预实验

**Files:** `experiments/pyproject.toml`及实际锁文件；`src/regresslab_experiments/{train_lora,infer,manifest,cli}.py`；`experiments/tests/test_training_contract.py`、`test_manifest.py`。该模块不进入Web训练队列。

**Interfaces:** `validate_profile(profile: dict, dataset_manifest: dict) -> TrainingProfile`；`prepare_supervised_rows(train_rows, tokenizer, profile) -> SupervisedBatchSource`；`train_checkpoints(profile, output_dir) -> list[CheckpointManifest]`；`infer_scope(model_manifest, inputs_path, run_manifest, output_path) -> PredictionRunManifest`。输入/输出manifest字段与03/19及机器合同一致，禁止接收future_predictions来决定训练或选择。

- [ ] 写TC-45/46/49/53/54的纯格式与边界测试：TRAIN外样本拒绝、prompt含gold拒绝、标签序列超长停止、缺base/adapter或父版本拒绝、run_id错拒绝；这些可在小型tokenizer夹具上测试，不下载真实模型。
- [ ] 在单独实验环境运行`python -m pytest tests/test_training_contract.py tests/test_manifest.py -q`，确认实现前失败；不强制CI跑GPU训练。
- [ ] 实现19默认配方、训练目标mask、checkpoint与断点状态、版本文件清单；CLI入口为`python -m regresslab_experiments.cli train-lora --profile <profile.json> --output <run-dir>`，`infer --model-manifest <model.json> --inputs <inputs.jsonl> --run-manifest <run.json> --output <predictions.jsonl>`。命令仅实验准备，不能伪称当前包已有代码。
- [ ] 先执行32步真实烟测TC-47，记录6GB设备环境、显存、耗时及恢复；DEV分类与100×3稳定性门槛不通过时按19修订/降级，不能直接跳正式C。
- [ ] 在正式评测前冻结profile与训练数据，保存steps100/200/300的v1/v2/v3；同一推理后端产生历史预测，v3预测须等套件冻结，完成后保存真实日志，不填预期效果。
- [ ] 核对保存/恢复前后完整参数与优化器状态；对实际运行写明通过、失败或未执行，再提交实验准备模块。

## M03O：Ollama与证据资格接入

**Files:** `models/ollama.py`、`provenance.py`、`stability.py`、API models/predictions/analyses、相应合同测试。

**Interfaces:** `inspect_local_models() -> LocalModelInventory`；`verify_frozen_model(model: ModelVersion) -> ModelInspection`；`validate_stability_report(report, old_model, new_model, dataset) -> StabilityEvidence`；`classify_evidence_mode(request, evidence) -> EvidenceMode`，DTO严格映射OpenAPI，不能另造字段。

- [ ] 写TC-48/50/51/52/58，断言服务器固定endpoint、digest漂移阻止发布、100例×3不稳定拒绝确认、DECLARED不变、描述模式C读取计数为0。
- [ ] `uv run pytest tests/contract/test_ollama.py tests/integration/test_stability.py -q`先失败；使用受控HTTP替身和工程记录，不能称替身验证真实模型效果。
- [ ] 实现已安装模型清单/检查、原始响应受限保存、evidence_mode和D-only正常终态；符合证据的确认仍走原一次C事务。
- [ ] 测试通过，再做真实Ollama连通与小样本推理，记录宿主机地址、运行时、模型digest及错误；不得为了接入安装任意用户模型或改已有标签。
- [ ] 同步生成DTO、迁移、UI和报告，提交完整接入切片。

## M04：scope严格的成对预测与导入

**Files:** models/adapters.py、api/predictions.py、PREDICT/IMPORT_PREDICTIONS handlers、tests/integration/test_prediction_sets.py。

**Interfaces:** `predict_batch(inputs: list[TextInput]) -> list[Prediction]`；`expected_ids(scope: PredictionScope, dataset_id: UUID) -> list[str]`；`validate_predictions(rows: Iterable[Prediction], expected: list[str], labels: list[str]) -> PredictionManifest`；`export_prediction_inputs(prediction_set_id: UUID) -> Iterable[TextInput]`。最后一个用于受审计CLI，C只有text/ID可读，不导出gold。

- [ ] 写TC-06/07/08；缺ID、多ID、未知标签、带gold全部拒绝；网络错误不变成ordinary_wrong。
- [ ] `uv run pytest tests/integration/test_prediction_sets.py -q`先红。
- [ ] 实现D+C与SUITE两种scope，CPU batch128、LLM按冻结配置单样本/受限并发、内部检查点、完整合法才SUCCEEDED。
- [ ] 测试绿；确认scope_hash和model/dataset声明不匹配时409。
- [ ] 提交。

## M05：成对指标与D候选发现

**Files:** analysis/metrics.py,discovery.py、api/analyses.py、DISCOVER handler、tests/unit/test_metrics.py,test_discovery.py。

**Interfaces:** 04中的compute_metrics/discover_slices；`create_analysis(request: AnalysisCreate) -> AsyncResource`。

- [ ] 写TC-09/10/11/30/35；夹具a6,b3,c1,d2；更改C/A不改变候选hash；n0抛INVALID_SCOPE；混淆分页与前50汇总一致。
- [ ] `uv run pytest tests/unit/test_metrics.py tests/unit/test_discovery.py -q`先红。
- [ ] 实现固定枚举、排序、去重与冻结；无候选直接SUCCEEDED/INCONCLUSIVE，不读C。
- [ ] 测试绿；抽查D案例列表与distinct负向翻转数一致。
- [ ] 提交。

## M06：一次独立确认与审查

**Files:** analysis/confirmation.py、confirmation repository、CONFIRM handler、api/slices review、tests/unit/test_confirmation.py、integration/test_confirmation_once.py。

**Interfaces:** 04 confirm_slices；`reserve_confirmation(analysis_id: UUID, candidate_hash: str) -> Job`；`review_slice(slice_id: UUID, flag: ReviewFlag, note: str) -> Slice`。

- [ ] 写TC-12—17/31，精确p、Holm、支持39/40、并发消费一次、人工备注不改结论。
- [ ] `uv run pytest tests/unit/test_confirmation.py tests/integration/test_confirmation_once.py -q`先红。
- [ ] 实现固定家族、component代表、统计状态、摘要及确认恢复；先登记使用权再读C。
- [ ] 测试绿；禁止UI读C/A原文；核对没有“安全通过”文案。
- [ ] 提交。

## M07：不可变回归套件

**Files:** suites/selection.py,export.py、BUILD_SUITE handler、api/suites.py、tests/unit/test_suite_selection.py、integration/test_suite_export.py。

**Interfaces:** 04 select_suite；`export_suite(suite_id: UUID) -> SuiteExport`；`suite_content_hash(payload: SuiteHashPayload) -> str`。

- [ ] 写TC-18/19/36：小义务夹具选择s1,s3，零池422，预算不足报告未覆盖，C/A禁止入选；分层截断与义务保留精确一致。
- [ ] `uv run pytest tests/unit/test_suite_selection.py tests/integration/test_suite_export.py -q`先红。
- [ ] 实现固定coverage_diversity_v1：覆盖→历史负翻→多样性、ID同分、5000上限、冻结快照和hash；通过TC-38元组/分数等价测试。组2/标签1不作为已证最优值。
- [ ] 测试绿；导出再读取校验内容一致，实际size不超过预算。
- [ ] 提交。

## M08：下一版本重放与报告

**Files:** suites/replay.py、analysis/reports.py、REPLAY handler、tests/integration/test_replay.py,test_report.py。

**Interfaces:** 04 judge_replay；`build_report(analysis_id: UUID) -> Report`；`render_report_html(report: Report) -> str`。

- [ ] 写TC-20/21/33：PASS/FAIL/ERROR区分、PRECOMPUTED等待输入/失败后新建、成功只排一次judge、HTML脚本转义与C原文不导出。
- [ ] `uv run pytest tests/integration/test_replay.py tests/contract/test_exports.py -q`先红。
- [ ] 实现真实SUITE范围预测、合法错判FAIL、失败判ERROR；JSON符合Schema。
- [ ] 测试绿；报告包含D/C分母、哈希、限制和版本。
- [ ] 提交。

## M09：中文完整工作台

**Files:** frontend/src/api/client.ts、router/index.ts、各08页面与组件；frontend/tests；e2e/regression-flow.spec.ts。

**Interfaces:** TypeScript类型由OpenAPI生成，字段不可手写另一套；前端只呈现统计，不计算p。

- [ ] 写TC-24端到端：项目→导入→训练→预测→分析→确认→套件→重放；无候选/支持不足也有正确出口。
- [ ] `npm test -- --run`、`npx playwright test e2e/regression-flow.spec.ts`先红。
- [ ] 按08实现状态、异步轮询、错误定位、幂等重试、token内存保存；使用真实API。
- [ ] 测试绿；360/1024宽度操作可用；P0无需解释模块，真实界面数据与证据模式均可演示。
- [ ] 提交。

## M10：恢复、部署与安全验收

**Files:** deploy、compose、cli doctor/demo、tests/integration/test_recovery.py,test_security.py、e2e/offline-demo.spec.ts。

- [ ] 写TC-22/23/25/26/29/32/34，覆盖文件发布与DB提交间崩溃和旧attempt回写，取消映射与人工resume边界。
- [ ] `uv run pytest tests/integration/test_recovery.py tests/integration/test_security.py -q`先红。
- [ ] 实现超时、取消、孤儿维护、备份检查与offline demo；完成10规定命令。
- [ ] 干净数据库/volume部署；记录真实性能、恢复、无secret日志结果；失败修复后再交付。
- [ ] 提交。

## M11：强基线与冻结实验

**Files:** lab/runner.py,baselines.py,strategies.py,evaluation.py,preregistration.py,change_log.py；experiments/configs/*.json；tests/unit/test_baseline_selection.py,test_experiment_boundary.py,test_algorithm_evolution.py。

**Interfaces:** `build_common_pool(rows, config) -> PoolSnapshot`；`select_cases(pool, obligations, vectors, method_id, budget, seed, params) -> SelectionResult`；`validate_run_registration(registration, prior_uses) -> None`；`evaluate_frozen_suite(suite, future_predictions, reference_groups) -> EvaluationRow`。字段与phase验证见17及selection-experiment-design.json；selector不得接收未来预测。

- [ ] 写TC-37—44：五基线的配额/同分/随机起点、消融不读被移除因素、共用池hash、开发与正式未来目标隔离、冻结拒绝、NA与晋级门槛、配置版本不可覆盖。
- [ ] `uv run pytest tests/unit/test_baseline_selection.py tests/unit/test_experiment_boundary.py tests/unit/test_algorithm_evolution.py -q`先红，确认因功能未实现失败。
- [ ] 实现17的5基线、complete、2消融与预注册可选history_first；实现SliceLine分组对照及lab统一C家族，所有selector共享最终审计分母。
- [ ] 测试通过后提交基线和边界模块；先跑R0夹具，不填真实效果。
- [ ] 默认固定初版时直接冻结正式注册；只有预先选择算法调整分支才跑DEV/独立开发链R1及最多一次R2，满足17额外链数和晋级条件，所有调整留change log。
- [ ] 冻结registration与配置hash；验证正式未来目标与开发目标不重叠，再执行`python -m regresslab.cli lab run --config <registration.json> --output <run-dir>`。正式D/C/A不得回流调参。
- [ ] 保存全部更新链、8方法、4预算、随机种子、原始预测、运行日志、成本和环境hash；无观察组为NA，不挑有利链，不将seed当独立模型实验。
- [ ] 提交lab-1.3产物索引，论文图表可追溯；新策略晋级生产前另修04、配置Schema、算法版本与fixture，M11不直接覆盖生产选择器。

## M12：最终交付核对

**Files:** 论文、用户/部署手册、软件验收记录、实验工件索引、答辩脚本。

- [ ] 逐项核对AT-01—06、真实版本来源、失败恢复、合同与论文图表，未执行项明确列出。
- [ ] 在干净环境重建应用，校验数据库与工件恢复及离线模型准备，记录实测环境与失败修复。
- [ ] 核对研究无增益与工程未完成两类状态，不因没有算法优势填造结果。
- [ ] 交付完整系统及来源/锁文件/真实记录；旧解释接口始终关闭，本任务不实现生成式说明。

## 实施节奏与变更

按M01→M08完成后再做大范围界面；M09可在M04后逐页接入，不阻塞算法。每项任务独立提交并记录测试证据；编码工具不得一次生成全部模块后才集成。需求/合同有变化先修本文档和相应测试，再改代码。用户未授权产品实现时只交付此计划，不自动开始安装或写产品代码。


## 1.3新增的实施与验收约束

M04须实现TC-49/55的run边界、原始响应和完整合法覆盖；LLM恢复不得合并不同run。M05/M06区分DESCRIPTIVE_ONLY和CONFIRMATORY，前者D后可出报告但不读C。M08将证据模式与来源状态纳入报告/suite快照。M09增加Ollama清单、父版本、训练step、来源真实性提示、稳定性及执行覆盖页面。M10实测Windows宿主机连接、模型/数据/工件备份。M11使用19真实语言模型链＋LR链，默认固定策略，不把原3开发/3正式及8内容版本当普遍毕业门槛；自适应调整仍按17严格条件执行。

优先顺序：M01/M02→M03T预实验→M03/M03O/M04→M05—M10→M11。若主训练预实验失败先记录和处理，不继续写“语言模型验证已完成”。M12只做最终交付核对；P1在全部核心交付后按明确变更实施。

本计划是供未来开发执行的文档，本次只修订设计；未运行这些产品测试、训练命令或部署。文档静态验证不能替代这些出口。


## Lab最终审计与全池预测入口

产品HTTP预测scope继续只允许D+C/SUITE，不开放AUDIT。完整研究评价由11§7.1的受审计lab命令处理：

```text
python -m regresslab.cli lab prediction-inputs --registration <registration.json> --target-model <model-version-id> --scope AUDIT|POOL --output <inputs.jsonl>
python -m regresslab_experiments.cli infer --manifest-kind lab --model-manifest <model.json> --run-manifest <lab-run-manifest.json> --inputs <inputs.jsonl> --output <predictions.jsonl>
python -m regresslab.cli lab prediction-validate --manifest <lab-run-manifest.json> --predictions <predictions.jsonl>
python -m regresslab.cli lab evaluate --registration <registration.json> --predictions <validated-lab-run-directory> --output <result-directory>
```

M11实现上述输入导出、预置LabPredictionRunManifest和最终评价；M03T的同一离线infer模块新增--manifest-kind product|lab（默认product），两个manifest严格判别。lab manifest见[Lab预测合同](../contracts/lab-prediction-run.schema.json)，含registration/evaluation/权重/推理/全部suite冻结hash及ID集合，不能导入产品HTTP。导出时同时生成PREPARED manifest，预登记模型白名单仅允许固定v1/v3。A和完整共同P'的未来预测均在套件冻结后；A逐例gold仅最终evaluate读取一次。失败或hash不符不出正式结果，不能把任意本地ID列表伪装成A。研究全池/A推理成本完整计入，不把查缓存当节省模型调用。

新增测试TC-61：未冻结全体suite或模型不在登记中时拒绝lab AUDIT/POOL输入导出；输入无gold、预测完整且单run、LAB_ONLY在HTTP导入被拒、最终A标签读取一次，错误时不发布正式评价。测试模块为tests/unit/test_lab_prediction_boundary.py与experiments/tests/test_lab_manifest.py，先红后实现，CLI入口字段与Schema一致。
