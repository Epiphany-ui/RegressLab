# v2 分阶段实施计划

状态：**未来开发计划，PLANNED_NOT_IMPLEMENTED**。本次只编写工程文档，不创建算法包、训练产物或虚构锁文件。原始依据为[研究产品范围](../../research/v2/source/PRODUCT.md)、[算法](../../research/v2/source/03-algorithm-spec.md)、[实验协议](../../research/v2/source/04-experiment-protocol.md)及[文献复现顺序](../../research/v2/source/02-literature-map.md)。论文主线为方法比较与实验；现有工作台承担证据浏览。

## 1. 交付层次和依赖

| 层次 | 状态 | 交付边界 |
|---|---|---|
| `backend/`、`frontend/`、现有SQLite与描述性Demo | 当前已有 | 保留启动、案例、历史、静态导出；v1划分/报告不更名为v2研究结果 |
| `lab/` 独立Python研究包 | 计划核心 | 数据/历史视图、风险与selectors、注册/冻结/evaluator、成本/统计/证据包 |
| `experiments/` 独立训练推理包 | 计划核心与受资源门控制的神经扩展 | CPU真实四版链；GPU依赖不进入Web后端；每种环境生成真实依赖锁 |
| Demo只读研究结果页 | 计划支撑 | 读取已验证工件、展示来源/分母/访问层/成本，不执行训练或统计重算 |
| PostgreSQL、认证、完整Worker、Ollama、API、网页调参 | 暂缓 | 研究完成不依赖这些产品工程；不得以页面数量弥补方法证据 |

核心依赖顺序为：`P0登记和测试边界 → P1领域/工件 → P2真实数据 → P3真实CPU链/G0 → P4统一基线/G1 → P5风险机制与强参考/G2 → P6正式冻结/解封 → P7完整报告/G3`。GPU短程分支在P3后评估，成功才进入神经迁移；可选确认和更多发现器在核心之后。

未来命令入口固定为 `python -m regresslab_lab.cli` 和 `python -m regresslab_experiments.cli`。现有 `python -m regresslab.cli demo/doctor` 保留，不为文档中的未来命令返回假成功。下表所有新增文件、接口和命令均为**计划目标**，当前不存在不算缺陷。

## 2. 各阶段的具体工作与出口

### P0：研究登记与可复现实验骨架

依赖：八份source原案已导入且保持不可变；现有Demo可以独立运行。

| 项目 | 计划内容 |
|---|---|
| 文件 | `lab/pyproject.toml`、实际生成的`lab/uv.lock`、`src/regresslab_lab/{cli,contracts,decisions}.py`；`tests/unit/test_registration.py` |
| 接口 | `validate_registration(payload, purpose)`区分provisional/development/formal；`resolve_approved_decisions`验证审批、范围和时间 |
| 工作 | 将研究问题、核心方法、访问层、预算、seed、≤6配置/≤2轮、数据与训练profile、来源/接受规则机器化；未决字段不伪装为已冻结 |
| 目标命令 | `cd lab && uv run pytest tests/unit/test_registration.py -q`；未来`python -m regresslab_lab.cli register --registration <file> --purpose development` |
| 输出 | 合法/非法登记fixture、差异清单、代码/环境指纹；现有文档schema与运行校验器的一致性记录 |
| 出口 | V2-I01、预算/访问层缺项测试通过；formal unresolved拒绝；不输出任何算法效果结论 |

先生成有内容和测试的最小包，再创建真实锁文件；不建立只有空目录的“已实现模块”。数据/权重/运行工件在Git外，仓库只提交代码、配置模板、小合成fixture与许可允许的材料。

### P1：时间、数据身份与不可变工件

| 项目 | 计划内容 |
|---|---|
| 文件 | `lab/src/regresslab_lab/{data/canonical,data/components,data/split,history,pool,artifacts,events}.py`；`tests/fixtures/v2/`；对应unit/integration测试 |
| 接口 | `build_history_view(dataset, f0_f2_runs)`不接收f3；`build_pool(history)`；`publish_artifact(temp, manifest)`；`verify_artifact(ref)` |
| 工作 | v2组件TEST80/10/10、DEV_MODEL/DEV_SELECTOR隔离；独立namespace；P=f2正确；文件hash/来源链；临时发布、拒绝覆盖、失败attempt留痕 |
| 目标命令 | `cd lab && uv run pytest tests/unit/test_temporal_pool.py tests/integration/test_artifact_integrity.py -q` |
| 输出 | FX-TIME/FX-BUDGET-ALIAS/伪hash/越界路径算例；history-view和pool-manifest；发布与恢复事件 |
| 出口 | V2-U01—03/U14、I02/I03通过；v1 Demo原fixture/50-25-25仍通过既有测试 |

只复用现有NFKC/JSON严格校验等稳定工具时，先通过独立fixture证明语义相同；旧`domain.py`的净下降发现、无gold特征限制和50/25/25不能直接作为v2算法默认值。

### P2：MASSIVE与独立外部意图数据审计

| 项目 | 计划内容 |
|---|---|
| 文件 | `lab/src/regresslab_lab/data/{massive,clinc,audit,provenance}.py`；`configs/data/*.json`；`tests/integration/test_dataset_provenance.py` |
| 接口 | `audit_source(local_files, source_profile)`→冲突/重复/跨分区/排除清单；`canonicalize(audit, approved_profile)` |
| 工作 | MASSIVE1.1 zh-CN；CLINC150仅in-scope闭集，OOS排除明确；源版本/许可/hash/实际计数/组件；不静默修gold，不把翻译作为独立语料重复 |
| 目标命令 | 未来`python -m regresslab_lab.cli audit-data --profile <file> --output <prep-dir>`；`prepare-dev --dataset <manifest> --profile <file>` |
| 输出 | 两数据集dataset-manifest、实际标签/角色支持量与清理损失；DEV两用途hash；数据不足/未知许可失败记录 |
| 出口 | V2-U01/U02、I03/I07的来源部分通过；数据G0材料就绪，未下载或未审计不能填真实hash |

数据获取入口在实现时核实官方来源并记录版本；CLI只处理受信本地文件。不要为绕过泄漏检查把跨分区样本移动到另一分区；预登记排除时删除整个相关组件并保留损失。

### P3：CPU四版本链与资源门G0

| 项目 | 计划内容 |
|---|---|
| 文件 | `experiments/pyproject.toml`与实际锁；`src/regresslab_experiments/{cpu,profiles,train_ids,infer,manifests}.py`；`tests/{test_cpu_chain,test_inference_contract}.py` |
| 接口 | `train_cpu_chain(train_view, profile)`→f0/f1/f2/f3真实产物；`predict_history(chain, inputs)`→单run完整标签/参考分数；目标预测写受控封存区 |
| 工作 | TF-IDF＋LR及一个预登记SGD/小MLP实现；三更新家族：数据增长、混合变化、训练配置变化。数据增长40/60/80/100；两家族开发＋一留出。每家族初始3条真实抽样/优化实现，不只改变lbfgs无效seed |
| 目标命令 | 未来`python -m regresslab_experiments.cli train-cpu --profile <file> --dataset <manifest>`；`predict-history --chain <manifest> --data <manifest>` |
| 输出 | chain-manifest、TRAIN抽样/优化记录、真实权重hash、保存恢复与合法覆盖证据、CPU wall/RSS/吞吐成本 |
| 出口 | 真实CPU部分G0；V2-I07/I08；开发与正式训练实现/种子列表不同且可追溯 |

**方向梯度兼容轨道（D-06工程草案）：**在TRAIN-only公共基底（例如f0的40% TRAIN）拟合并冻结词表、IDF、类别和模型形状；各版只实际更新分类器，仍按预登记40/60/80/100或其他配方训练。所有方法共用同一链，清楚标记与每版重拟合向量器的差异。可另用同固定基底的SGD/MLP；不把不同词表/IDF的LR系数零填充后冒充对齐。最终表示方案须G0前/正式登记前批准。

GPU是并行的受控分支：先在DEV_MODEL执行一次预登记短程训练和完整标签输入检查，测峰值显存、训练/推理wall、吞吐、合法性与稳定性，再估算训练、历史/目标推理、保存和复验总量。初始累计20 GPU小时是护栏，不是性能承诺；预算不足不扩展三条神经链。真实步数、精度、分类头/生成标签、序列长度与重复资格在资源profile中决定，不直接照搬旧v1三个checkpoint配方。不可静默截标签/原文或丢掉难例。

### P4：统一基线、分数合同与信号门G1

| 项目 | 计划内容 |
|---|---|
| 文件 | `lab/src/regresslab_lab/selectors/{base,random,stratified,past_flip,uncertainty,kcenter,facility}.py`；`representations.py`；`tests/unit/test_selectors.py` |
| 接口 | `select(history_view, pool, config, seed, max_budget)`→有序ID/理由/成本；历史接口不含目标句柄；`score_contract`注明类别分布含义 |
| 工作 | Random、Stratified、PastFlip、四种f2不确定性、KCenter、Facility；同P/表示/预算。固定排序/递增方法取前缀；Stratified各预算最大余数配额独立计算。20个随机seed按方法登记，确定方法只跑一次 |
| 目标命令 | `cd lab && uv run pytest tests/unit/test_selectors.py tests/unit/test_reference_scores.py -q`；未来开发模式`select --study <id>`、`evaluate --study <dev-id>` |
| 输出 | 开发链全部P/R*、零翻转比例、历史未见/复发事件、seed内波动、成本；不访问正式f3 |
| 出口 | V2-U08/U09/U12/U14；G1的注册有效链/事件变化检查。这里只允许开发诊断，缺完整核心方法不能冻结正式矩阵 |

参考概率生成不可用时先做标签层管线和fixture；CPU应优先提供合法`predict_proba`完成四种强不确定性。生成式参考版本只有首token分数时标不满足参考分数合同，不能假装已完成同层比较。

### P5：HGC机制、近邻强方法和G2

| 项目 | 计划内容 |
|---|---|
| 文件 | `lab/src/regresslab_lab/{groups/enumerate,groups/risk,groups/adapters,selectors/hgc,selectors/risk_top,selectors/risk_lr,selectors/behavior_anchor,selectors/legacy_adapt}.py`；`experiments/.../gradient_direction.py`；对应fixture/tests |
| 接口 | `discover_risk_groups(history)`；`fit_risk_predictor(dev_history, cutoff)`；`marginal_gain(state, candidate)`；白盒独立`rank_direction(old_checkpoint,target_weights,allowed_inputs)` |
| 工作 | HGC m30/k3/λ.5初值、30组/256锚点、全0退化Facility；Risk-Top、Risk-LR、Behavior-Anchor、Legacy-adapt；CPU一阶方向Grad-PD；至少安装核查SliceLine/DivExplorer之一 |
| 目标命令 | `cd lab && uv run pytest tests/unit/test_risk_weights.py tests/unit/test_selectors.py tests/integration/test_method_adapters.py -q`；`cd experiments && uv run pytest tests/test_gradient_direction.py -q` |
| 输出 | 全4.1方法method manifests、白盒参考manifest、论文/代码版本与适配差异；6配置以内/2轮以内完整开发结果；四类机制模拟与主要消融 |
| 出口 | V2-U04—13、I02/I09；G2通过或明确停止调参转比较研究。缺Risk-LR/Behavior-Anchor/方向参考不能以其他方法数量代替 |

Risk-LR预测H_t的输入严格截止于f_t：只有H_<t/E_<t及f_t参考分数（若该访问层允许），t=0带cold-start标记；正式f2→f3可H0/H1、不可H2。训练仅DEV_SELECTOR开发历史，记录其模型选择偏差；若没有正例，不能偷用正式目标补训练数据。

群体收缩率是探索性风险特征，不是p值。FX-RISK净零高翻转必须保留。SliceLine不能直接喂负的NF−PF后沿用非负剪枝保证；旧正确子池上的翻转二值适配注明分母。至少一个可安装实现失败时，记录依赖/版本/失败并解决或重新批准比较范围，不能写已完成外部核查。

### P6：正式注册、全矩阵冻结与一次目标评价

| 项目 | 计划内容 |
|---|---|
| 文件 | `lab/src/regresslab_lab/{registry,runner,freeze,access,evaluator,resume,costs}.py`；`tests/integration/{test_access_boundary,test_freeze_resume,test_evaluator}.py` |
| 接口 | `expected_cells(registration)`；`freeze_matrix(registration, suite_refs)`；`evaluate(freeze, sealed_target_handle)`；`resume_attempt(event_log, identical_inputs)` |
| 工作 | 全方法/配置/预算/seed注册；真实来源/hash；各层输入允许清单；目标根在selector根外；预批准UNAVAILABLE限制结论，运行失败不能删cell；断点恢复和成本不重置 |
| 目标命令 | 未来`python -m regresslab_lab.cli register --registration <file> --purpose formal`；`select --study <id>`；`freeze --study <id>`；最后`evaluate --study <id>` |
| 输出 | `registration.json`、各suite、`freeze/matrix-freeze.json`、UNSEALED事件、evaluation-result与逐笔成本 |
| 出口 | V2-I01—08/I10；全部必需单元齐全才解封；伪hash、目标提前读取、矩阵遗漏均失败 |

正式registration是新study的不可变快照，引用准备好的真实工件并保留development父hash。先重验数据/历史到HISTORY_READY，锁定全部配置再SELECTING。formal因子不能留未决值。评价中断可在同session恢复，不允许回到选择阶段；任何曝光不得改名后恢复“未见目标”。

P6的核心门禁只覆盖`CORE_PRE_TARGET`，声明白盒/有限探测按独立能力登记。可选TARGET_FULL_POOL基线使用D15的`ENHANCED_TARGET_ACCESS`：其配置在主目标前预登记，父主矩阵冻结后再冻结增强registration并取得输入，运行、冻结增强套件后评价；禁止回写父主比较。不要实现逻辑上要求全池基线先选样后才准读取其必要输入的单一门禁。

### P7：完整报告、证据包与G3

| 项目 | 计划内容 |
|---|---|
| 文件 | `lab/src/regresslab_lab/{metrics,statistics,aggregate,reports,view_bundle}.py`；现有backend的只读bundle导入/查询模块；frontend研究结果页；`e2e/research-v2.spec.js` |
| 接口 | `evaluate_metrics(common_pool,target,ordered_suite)`；`aggregate_within_chain_then_compare`；`export_view_bundle(validated_run)`；HTTP只读结果契约按迁移文档实现 |
| 工作 | 同P的Recall/Precision/Enrichment、新错/复发分母、零R→NA；预算别名、各访问表、链内seed聚合、链级配对与两本账；转义导出；保留失败与无收益 |
| 目标命令 | 未来`python -m regresslab_lab.cli aggregate --study <id>`；`verify --study <id>`；`publish-view --study <id>`；未来`cd e2e && npm test -- research-v2.spec.js` |
| 输出 | 结果表、完整预算曲线、成本表、消融/失败案例、可重算索引及只读bundle；研究报告与应用报告分格式 |
| 出口 | V2-U14—16、I11、E01—04与G3；论文结论按预登记规则，证据不足不强写优越/非劣 |

界面复用规则见[05](05-demo-migration.md)；只接受完整封存manifest，不允许浏览器送f3字段给selector。未完成评价的研究只展示历史、候选及“未执行”；不把旧Demo的INCONCLUSIVE或合成结果当新方法效果。

05描述的最小只读证据Demo是可选的UI0纵切面：P1合同/验证器可用后，可用明确的v2合成证据包先验证界面，真实实验仍按P2—P6推进。它不提前完成P7真实结果汇总，也不应抢占数据、强基线和G0资源试验；最近小迭代默认先做lab边界骨架。

## 3. 时间安排与最近一个小迭代

| 时段 | 计划投入与交付 | 范围保护 |
|---|---|---|
| 2026-10下旬至11月中旬 | 与导师确认研究问题/接受口径；完成文献来源和工程登记；可选小迭代仅做CPU合成fixture与边界骨架 | 不下载大权重或承诺正式实验；当前任务只产出文档 |
| 2026-11月下旬至12月 | 备考优先，只维护必要故障/决策记录和资料 | 不安排连续开发、GPU矩阵或新UI工程 |
| 2027-01 | P1—P3数据审计、真实CPU四版链、G0资源实测；P4小规模强基线与G1 | 先信号和资源后扩模型；GPU20h初始护栏 |
| 2027-02 | P4—P5全核心、独立外部意图数据、两家族开发及留出家族；≤2轮后G2 | 最多6个λ/m配置；机制消融不全乘积 |
| 2027-03 | P6正式登记/冻结/一次解封，P7成本与完整结果；资源通过才补神经迁移 | 不拿正式结果再调参或更换输家版本 |
| 2027-04 | 复现、失败条件、论文/案例和原型整理 | 负结果可交付；不以增页面代替研究贡献 |

建议最近小迭代按累计8—12小时的可缩减预算组织，属于待安排工作量而非承诺工时：

1. 约2小时：审定未决字段、方法矩阵、Grad-PD固定坐标方案和G门；保持source不变，只维护决策稿。
2. 约3小时：未来建立lab最小包与FX-TIME、FX-RISK、伪hash/无f3路径fixture，先验证失败；不立即实现全部selector。
3. 约3小时：P/时间前缀/风险权重/不可变manifest最小实现与测试，证明没有“最近历史在P非零”的错误假设。
4. 剩余时间：准备真实数据审计profile和CPU配方模板，列来源/许可/包兼容问题；GPU只写预实验登记，实际短训放在G0资源阶段。

超过预算时优先留下可复现测试与清晰未决项，不以加班侵占备考。真实方法效果、CLINC外部验证、CPU梯度参考和全核心方法不因小迭代结束就标已完成。

## 4. 正式登记前必须解决的选择

| 登记项 | 当前依据/初始建议 | 冻结要求 |
|---|---|---|
| DEV两个用途、v2 split namespace/seed/算法 | DEV50/50与TEST80/10/10为工程初始稿 | 组件清单与实际类别支持；不能沿用v1的角色身份 |
| CPU链、混合/正则化配方、开发/正式种子 | 增量40/60/80/100；每家族先3条；2开发＋1留出 | 固定实际抽样/优化机制，禁止看正式结果挑版本 |
| Grad-PD坐标与模型架构 | D-06固定TRAIN-only基底及同类表/形状草案 | 所有方法同链；参数不可比即不运行错误参考 |
| 神经模型标签接口与资源 | 0.6B LoRA候选；分类头/生成标签、步数/精度未定 | DEV短程实测；完整分数定义；累计20h调整须先于正式目标 |
| Behavior-Anchor | 行为正确性/合法参考置信度聚类的适配 | 距离、簇数/预算关系、代表/补齐/空簇、随机性与成本固定 |
| Risk-LR | L2、C=1、balanced；严格历史前缀 | 特征映射、cold-start、开发拟合数据、分数版独立登记 |
| 表示/群体/锚点 | m30/k3/λ.5、30组、256锚点；P-only TF-IDF工程稿 | 算法、同分、配额/hash和向量器完整参数；修订留版本 |
| G1/G2量化门、主比较器 | 来源给定方向，详细阈值仍须审批 | 最低链/翻转数、接近容限、成本上限、选择器规则先定 |
| 正式接受与推断 | +.05实用增益、−.03非劣界/20%成本为源文建议 | 导师认可、可识别的独立实现/相关性、统计家族；不显著不等于持平 |
| 外部方法包 | SliceLine/DivExplorer至少一项安装核查；Grad-PD先CPU方向参考 | 实现版本、许可、论文版本、原样/重实现/适配差异与失败记录 |

这些是有截止点的工程决策，不是允许在正式结果后继续选择的菜单。正式必需方法若运行失败阻止矩阵冻结；预批准不适用仅限定该访问层/模型上的结论，不能为HGC删掉强比较器。未完成核心比较时直说缺项。

## 5. 可选扩展与停止规则

C净下降确认、多发现器竞赛、语义/嵌入族、MASSIVE en-US、完整IRT、CASPER/RiskBlend/MetaSel增强访问适配均在核心之后。若开展发现器C审查，每方法同K=10及统一候选家族；不得把这个K与HGC30风险组混同。增强方法目标探测和全池预测完整记账；C/A不进入主P的未来召回分母。

全池增强可复用研究金标准物理执行，但必须记录其实际方法访问与公平部署口径，不能重复记物理支出或把已有缓存等同全池访问免费。其套件的冻结晚于主矩阵是协议分支的一部分，报告清楚呈现该差异。

GPU失败保留CPU研究并限定语言模型结论；G1没有自然翻转时停止相应检出主张；G2无稳定收益时停止堆叠；G3负结果不返工调参。整个工作是否达到学院要求由导师依据真实证据判断，计划不把“保证赢基线”作为完成条件。

## 6. 每个阶段提交的检查单

每阶段提交：实现与schema差异、对应V2验收ID、实际命令与结果、来源和环境清单、失败/未执行项、成本、下一关决策。原始数据/权重/私有目标不入Git；小合成fixture必须明确synthetic。验收ID与G0—G3的详细对应见[06](06-validation-plan.md)，状态/成本及目标解封顺序见[04](04-workflow-and-costs.md)。

只有真实实现后才在当前状态说明中把能力从“计划”改为“已有”；只完成文档、schema或文件夹不视为实验框架、模型更新或方法收益已完成。
