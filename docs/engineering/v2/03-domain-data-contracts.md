# v2 领域、数据与研究工件合同

状态：**工程 DRAFT，尚未实现、未批准正式研究冻结**。本文把八份不可变[研究源文档](../../research/v2/source/README.md)转为可审查的离线合同，不创建新 HTTP API，不实施 HGC 或其他论文方法。研究假设以[算法源文档](../../research/v2/source/03-algorithm-spec.md)和[实验源文档](../../research/v2/source/04-experiment-protocol.md)为准。这里的确定性补充必须经过研究冻结，不能默认为已获导师认可。

范围及待决项见[01](01-scope-and-decisions.md)，组件隔离见[02](02-architecture.md)，状态与成本见[04](04-workflow-and-costs.md)，已有 Demo 的迁移边界见[05](05-demo-migration.md)，合同验收与实施顺序见[06](06-validation-plan.md)、[07](07-implementation-plan.md)。机器形状以[research-artifacts.schema.json](contracts/research-artifacts.schema.json)为准，使用方式见[合同说明](contracts/README.md)。

## 1. 研究对象与两条隔离轴

一次研究目标是一条真实四版本链 `f0 → f1 → f2 → f3` 中的一次未见相邻更新 `f2 → f3`。`f0/f1/f2` 是历史，`f2` 是当前参考版，`f3` 是待评目标。三个相关 checkpoint 不能代替这条四版本链；四个 checkpoint 也只是一条训练实现，不能算四次独立实验。

样本角色精确使用 `TRAIN / DEV_MODEL / DEV_SELECTOR / D / C / A`。官方 TRAIN 仅训练任务模型；DEV 按组件分为模型开发和选样开发；官方 TEST 的 D/C/A 比例为 80%/10%/10%。D 为核心历史风险建模和套件候选，C/A 只供预登记的诊断扩展。正式选样不读取 C/A；正式未来召回的分母来自同一 `P⊆D`，不能用 A 的错误作分母。

`P={i∈D: f2(x_i)=gold_i}`。所有 D 历史行都可用于群体风险估计，最终套件仅从 P 选择。旧 Demo 的 `DISCOVERY/CONFIRM/AUDIT`、50/25/25 分区、三版链、人工合成预测及确认状态均不能自动登记成 v2 正式证据。

## 2. 记录身份、组件与标签

以下为 **D01/D02 工程决策草案，须研究冻结**：

- `source_i = "si:" + SHA256(CJ({domain:"regresslab.v2.source-i.v1",dataset_family,source_release,locale,source_record_key}))`；v2 `sample_id` 的语义就是 source_i。清理、排序和导出不重编号。
- 有官方行 ID 时，`source_record_key` 保存官方 ID 的精确字符串；无官方 ID 时，使用原始文件 SHA256 加原始 JSON Pointer 或 JSONL 行位置。该映射在首次无模型结果的数据审计中封存，不能对清理后文件重新编号。更换数据 release 会产生新身份。
- `source_group_i = "sg:" + SHA256(CJ({domain:"regresslab.v2.source-group.v1",dataset_family,source_release,parallel_record_key}))`。MASSIVE 的 parallel_record_key 使用同源 ID，省略 locale；无已知平行对应时使用 source_record_key，不能猜测 scenario 就是独立模板 ID。
- 归一化采用 NFKC、连续 Unicode 空白折叠为单空格、首尾去空白；保留大小写、标点与否定词。原 text 留作展示，归一化文本仅用于指纹、重复审计和冻结特征。
- 按相同 source_group_i 或相同归一化文本 SHA256 作传递连通组件；`component_key` 取组件内 source_group_i 的 UTF-8 字节序最小值。不同语言的同源行不能跨角色。
- 跨官方 TRAIN/DEV/TEST 的组件、同归一化文本不同 gold，默认使版本拒绝。若采用清理 profile，必须在任何正式模型结果前批准，整组件剔除，记录原 locator、原因、分区/标签损失和 hash；不能只删不利测试行、移动分区或改 gold。

`DatasetRow` 字段是 `source_i,source_group_i,source_record_key,locale,source_partition,text,gold_label,component_key,role,normalized_text_sha256`，拒绝未声明字段。source_partition 为官方 `TRAIN/DEV/TEST`；role 为研究角色，二者不可互相覆盖。训练标签集合固定、UTF-8 字节序排序，DEV/TEST 未见 TRAIN 标签时停止导入。CLINC150 闭集 profile 必须明确剔除 OOS 并保存其排除清单；不能以 OOS 当第151个意图。

D01/D02 还提出：DEV 组件先以 50/50 作为开发可行性草案；TEST 按源方案 80/10/10。候选实现对组件使用 `SHA256("split-v2|"+seed+"|"+component_key)` 的前8字节无符号整数除 `2^64`；DEV 按冻结阈值分，TEST 按 `.8/.9` 阈值分。seed、DEV 比例、是否改为标签分层组件分配都必须在正式结果前批准。`SplitRule` 不替代对所有角色实际类别支持、组件数和损失的审计；不能为了凑整比例拆组件。

## 3. 来源、权重、推理和单次预测

`ModelChain.versions` 精确包含 f0/f1/f2/f3。每版保存真实 weights manifest、TRAIN 清单、训练 profile/seed、step、父版本和推理合同；按 slot 顺序及父链验证无环。数据增长链起点比例为 40%/60%/80%/100%；具体采样、混合变化、训练配置和四个 LoRA checkpoint 的预算在开发预实验后冻结。仅给确定性 lbfgs 更换 random_state 不足以证明独立训练实现。

权重身份覆盖所有实际推理所需的拟合产物：CPU 的词表/IDF/系数，或神经模型 base＋adapter。推理身份覆盖输入、标签映射、tokenizer、backend/version、精度、解析器、完整解码和环境。同链保持约定的推理流程；明确登记的训练配置变化不能伪装成只换权重。`DECLARED` 表示外部声明，真实 hash 和格式校验不能把它升级为独立认证。

**D06 白盒对齐草案：**Grad-PD/GBV-PD 需要同一参数坐标、类顺序、词表和IDF基础，不能对不同维度或重排后的系数直接相减。主白盒兼容 CPU 链建议仅在共同 TRAIN 基础子集（f0 的40%）拟合并冻结向量器/IDF及模型形状，再对40/60/80/100%数据真实更新分类器；所有选样方法共用该链，不为梯度方法另换有利模型。ModelChain 保存 representation_id/representation_manifest、param_coordinate_sha256、whitebox_alignment/alignment_manifest；白盒可用时对齐摘要和清单不能为空。逐版重拟合向量器的链默认 INELIGIBLE，除非在正式结果前给出已验证的坐标映射并单列协议；不能任意补零、相减后宣称复现。固定基础的SGD/MLP可另预登记。这是工程及实验设计补充，须研究冻结，不能伪称源文档已指定。

`PredictionRun` 是唯一 run_id、固定模型身份、固定角色和 expected source_i 集合的一次完整执行。每行 `PredictionRow` 必有 `source_i,run_id,prediction_label,raw_response`，可有 probabilities 和 latency_ms，不接受 gold 字段。原始响应受限保存，不用事后拼造的正确 JSON 代替实际返回值。

成功门禁同时要求：expected IDs 与 actual IDs 一一对应；无缺失、重复、额外行；所有行同一 run_id；label 在冻结 label_vocab；原文按冻结 parser 重新解析后与声明标签一致。`label-json-v1` 仅接受一个、且只含 label 键的对象，拒绝重复 JSON 键；`label-literal-v1` 精确匹配，不 trim 或猜测映射。JSONL 必须 UTF-8，无非有限数、重复键或不完整行。

覆盖率单列 `expected_count,legal_count,missing_count,duplicate_count,extra_count,invalid_count,failed_count,ratio`；空 scope 的 ratio 为 null，不能生成普通准确率。非法输出/超时是执行问题，不能静默删行、替换 gold、按错回答反复采样，或当作普通分类错误。可能有随机性的推理失败后，新建整份 run，不能拼接不同 attempt 的成功行。缓存标 `CACHED_PLAYBACK`，不称新推理或独立稳定性重复。旧 Demo 的稳定性门槛不自动成为 v2 的神经预测充分证据；具体复跑资格须在研究注册中冻结。

### 概率访问层

probabilities 如存在，必须按 ProbabilityContract.label_vocab 的同一完整顺序覆盖全部类别、每项有限且在 [0,1]，逐行和在冻结容差 `1e-8` 内为1；该容差属于 **D04/D05 工程草案**。一份登记为分数完整的 run 不得只给部分行概率。分类头 softmax 与完整标签序列似然归一化分开命名、计费；序列模板、EOS、长度归一化及候选标签归一化规则均进入配置 hash。

**不接受首 token 概率充当完整意图分布。** 共享前缀的标签尤其不能如此实现 DeepGini。完整序列似然归一化也不等于已经校准的真实概率；其适用限制应保留。没有合法分数时，预登记降为标签访问层，分数基线记 `UNAVAILABLE_PREAPPROVED`，不能填0、假装已完成或在看 f3 后决定省略。

## 4. 选择器唯一可读的 HistoryView

HistoryView 为严格投影，仅包含 f0/f1/f2 历史 run 引用、D 或 DEV_SELECTOR 的历史记录、标签合同、固定特征、表示配置和历史派生统计。schema 不接受 f3 slot、target prediction、sealed-target path、全 ModelChain 路径或任意额外字段。`chain_identity_sha256` 和 `registration_sha256` 如传给 selector，只是不可解析的身份值；不授权打开包含目标引用的完整注册或链文件。

正式 selector 不加载完整 StudyRegistration/ModelChain；调度器把当前 cell 所需的历史/池/方法配置及 opaque registration hash 投影为白名单输入。sealed target 存在 `var/sealed-targets/<study_id>/<chain_id>/` 等 selector 可读根之外。目录名不是隔离保证：必须检查解析后真实路径、符号链接、文件句柄、进程环境、网络、共享缓存、日志和代码可读性。详情见02/06。

gold_label 在 v2 是允许的风险特征。第一轮特征精确为 gold_label、length_bin、has_negation、has_digit、has_question_mark；长度边界与中英文否定词表在开发集冻结。不能沿用旧版“gold 禁入特征”的限制，也不能凭此把 f3 错误标签、任意自由元数据或 LLM 生成条件放入 selector。

Risk-LR 开发训练的任务若是预测转移 t 的 H_t，协变量只允许 H_<t、E_<t 及当时已知输入/参考特征，**不能使用同一 H_t 作“历史翻转次数”特征**。正式预测 f2→f3 可用 H0/H1 和相应机会数。无此前历史时填0且另有 availability 标志，不能把“未观测”解释为“观测到无错误”；该约定进入 HistoryView.history_feature_contract 和开发训练映射 hash。

## 5. HGC 派生量和确定性草案

源方案参数起点为 m=30、min opportunities=10、最多30组、Jaccard阈值0.9、λ=.5、k=3、锚点最多256；核心开发最多 λ∈{.25,.5,.75}×m∈{10,30} 六配置，k=1单列机制消融。主预算100，完整预算20/50/100/200。合同记录这些配置，不实现或预判其效果。

历史仅有转移 f0→f1、f1→f2。全局旧正确机会数为0时，该整个转移被排除并记录原因。对全局有效的转移，组机会 e<10 时 u=0并保留 low support；**该零值仍进入 q 和 mean(u) 的全局有效转移分母**。不能把低支持转移从 q 分母删除来抬高重复风险。两次相关转移不算独立训练重复；群体的 w 也不是 p 值、置信下界或已经校准的未来概率。

若两个全局转移都无有效旧正确机会，不执行除零，记录无有效历史原因，q/w置0并走无正风险的代表性fallback。该情况是信号不足，不能解释为群体已证明无风险。

RiskTransition/RiskGroup 保存机会数、负向翻转数、p0、收缩率、uplift、低支持标记、q/w/归一化权重、D/P支持和成员hash。业务校验必须复算 b≤e、全局和组计数、valid flags 以及全部公式。风险组仅标 `NOT_PERFORMED` 统计确认；不能因高风险率把它写成已确认净下降。

以下补足源方案未完全指定的确定性行为，均为 **REQUIRES_RESEARCH_FREEZE**：

| 决策 | 草案及边界 |
|---|---|
| D03 群体次序 | w 降序、P 支持降序、canonical predicate 的 UTF-8 字节序升序；按此序在 D 成员上 Jaccard≥.9 去重，再保留至多30个 P 支持>0的组。主排序/支持次序是工程补充，需冻结。 |
| D04 锚点 | a=min(256,|P|)，按 P 中 gold 比例最大余数分配；余数同分按标签 UTF-8 升序，各类内部按 `SHA256("anchor-v2|seed|"+source_i)`、source_i 升序取样。预算小于类数可有零配额；不添加未经说明的每类保底。U 在全部预算和方法所需相同条件下固定。 |
| D04/D05 表示与有限精度 | 初始建议仅 P 拟合归一化 char TF-IDF(2,4)、min_df=1、max_features=20000、lowercase=false、sublinear_tf=true、L2、float64；源方案允许 D/P 拟合，选哪一个须冻结。K 非负夹到[0,1]；任意零向量与其他向量相似度0。锚点相似度仅 a×n，不建 n×n。 |
| D08 同分、随机和预算 | greedy 边际直接比较 float64 值，同值按 source_i 字节升序；不临时引入 epsilon 把近似值并列。Random/PastFlip 同分/分层类内/KCenter 起点的20 seed 列表预登记；伪随机算法或 hash 域也登记。HGC 固定一个 J，所有预算取同一贪心序列前缀；Stratified 不是强行套同一前缀。 |
| D06/D09 链与统计 | 开发/正式 TRAIN 实现种子互斥、主比较器、实用门槛、非劣界和成本条件等在正式解封前批准；源方案 .05、.03、20% 和初始20 GPU小时仍是拟定门槛，不写成已验证或导师已同意。 |
| D06 白盒坐标 | 对主CPU梯度参考冻结共同TRAIN基础向量器及参数坐标；跨版拟合基础不同的链须标白盒不可用或预先验证映射。所有方法共享同一链。 |

P 不自动截断为5000。旧 Demo 的上传护栏不定义 v2 的候选池。资源不足时应停止并登记新协议或预批准子采样研究；不能静默截断、改变所有方法分母后仍引用原研究设置。PoolManifest.pool_cap 在本草案中必须为 null。

若没有正权风险组，记录 `NO_POSITIVE_RISK_REPRESENTATION_ONLY`，直接以代表性目标运行，不制造风险组。空 P 记录 `EMPTY_POOL`，各预算实际size=0，评价适当记 NA。该运行仍需留在注册矩阵及失败/无信号统计中，不能挑选有退化的链。

## 6. 方法登记、访问层与冻结矩阵

MethodRegistration 逐方法记录 method_origin（原实现/重实现/适配/启发）、论文版本、源码commit、实际实现commit、目标/配置hash、访问能力、seed策略、未实现差异和成本。修改论文目标后必须改名或加 adapt 后缀。建议稳定 ID 为 random、stratified、past-flip、ref-maxprob、ref-margin、ref-entropy、ref-deepgini、kcenter、facility、risk-top、risk-lr、behavior-anchor、legacy-adapt、hgc；梯度和目标增强方法按实际适配另命名。

| access_tier | 允许新增信息 | 评价展示 |
|---|---|---|
| HISTORY_LABEL_ONLY | text、gold、f0/f1/f2标签、冻结文本表示 | HGC等核心标签层 |
| REFERENCE_SCORES | 上述信息＋f2完整合法分数 | 参考不确定性层，不能偷用f3 |
| TARGET_WHITEBOX | 声明的历史梯度、f3参数/权重差 | GBV-PD/Grad-PD单列；无f3全池推理不等于无目标访问 |
| TARGET_PROBE | 预登记数量的f3探测 | 探测执行完整计入预算和成本 |
| TARGET_FULL_POOL | f3全池输出/概率 | RiskBlend/MetaSel等增强访问，不能混入零目标访问主表 |

HistoryView 不是白盒或探测上下文。增强方法只能由另行受审计的适配器取得所声明的目标能力；不能给所有 selector 挂载目标目录再凭口头约定不用。零目标访问方法以及全部方法的实际读取日志与声明比对；Schema 无法证明程序诚实，也无法防止在任意字符串中隐写结果。

PastFlip的逐例分数按历史负翻次数/旧版正确机会数；机会数为0时，工程草案将分数置0并保留`NO_HISTORICAL_OPPORTUNITY`标记，不假定风险已知为0。可选替代处理须开发登记，不在正式结果后调整排序。固定输入的同分随机顺序在各预算复用，避免把预算差异混入随机性。

StudyRegistration 先有 PROVISIONAL 开发快照，可保留未决配置和尚未生成的引用；只供 fixture/development。正式 SELECTING 前，必须生成新的 FORMAL/FROZEN 不可变注册版本：真实 dataset/chain/history/pool/method refs、全 chain×method×budget×seed×access 的 expected_cells、主比较器、统计计划及所有审批均齐全。parent_registration_sha256 保留谱系；不能覆盖旧注册文件或改名洗掉已看目标的事实。

`cell_id="cell-"+SHA256(CJ({registration_identity,chain_id,method_id,configuration_sha256,access_tier,budget,selection_seed}))` 为 **D08 草案**。registration_identity 是显式预先生成并冻结的稳定UUID，独立于通用artifact_id；不能把包含 cell_id 的最终 registration hash 反向塞入 cell_id 而形成循环。expected_cell_set_sha256 对排序后的全部 cell 核心记录计算；seed重复和同一配置重复cell由业务层拒绝。

SuiteFreeze 只冻结一个 cell，含有序source_i、actual size、方法/历史/P/组/表示/锚点依赖hash、trace及fallback。应逐例验证成员均在同一 P、无重复、选取数量等于 min(B,|P|)，且 HGC 跨预算符合冻结的共享前缀。Suite 不包含 f3 结果。

FreezeMatrix 是一次完整门禁。必须与 FORMAL 注册核对 expected cell 的全集，而不是“当前目录里恰好已有的文件”；所有 required cell 均 FROZEN，运行失败的 required cell 阻止冻结。`UNAVAILABLE_PREAPPROVED` 仅可在目标访问前审批，并带明确范围降级/结论限制；不能把失败、缺失或未实现强基线事后改为 unavailable。缺合法分数可预登记标签层研究；CPU方向梯度强参考不能无说明删掉后仍声称已完成全部核心比较。

### D15：主比较与全池增强访问的时序分支

`StudyRegistration / FreezeMatrix / EvaluationResult`共同携带`comparison_scope`和`parent_core_freeze_sha256`。`CORE_PRE_TARGET`的parent为null，expected_cells不得含TARGET_FULL_POOL；其中的主标签/参考分数方法零目标访问，独立白盒/有限探测只使用其预登记能力。全池金标准授权字段为`full_target_prediction_unseal_authorization=ONLY_AFTER_FREEZE_MATRIX`，不是禁止白盒读取的含糊`target_access`布尔值。矩阵记录`undeclared_target_access_before_freeze=false`，并由访问审计核实。

`ENHANCED_TARGET_ACCESS`仅用于需要TARGET_FULL_POOL的增强表，parent必须为实际主矩阵hash，授权字段为`AFTER_PARENT_CORE_FREEZE_AND_OWN_REGISTRATION`。其方法/配置应在主目标曝光前写入预登记提案，取得全池输入前将增强registration冻结；取得输入后才能运行增强选择、冻结其自身矩阵，再由evaluator计分。此分支不得修改父主矩阵、风险、锚点或套件，不能冒称目标未知的主比较。无需在本轮实现增强分支，但合同不能要求它在读取自身必要输入之前先产生全部套件。

SelectionCell明确含`configuration_sha256`和`budget_semantics`。主标签/参考/白盒使用`UNIQUE_SELECTED_POOL_SAMPLES`；TARGET_PROBE使用`TOTAL_TARGET_EXECUTIONS_PROBES_INCLUDED`；全池增强使用`FULL_POOL_ACCESS_REPORTED`。初始探测适配限定唯一P内样本、每例一次调用、所有探测ID必须包含在最终计分套件，额外选择仅补至有效预算，因此实际探测＋补测调用不超过B；不满足该约束的论文适配需新预算合同，不能套用此草案。重复探测/重试费用照记，失败不能藏在去重后数量里。

原论文名不决定访问层，实际取得的信息才决定。增强分支的全池输入费用属于方法访问成本；评测器为取得金标准的全量运行另记研究成本，物理执行不得双重计费，复用时也不能把查缓存当成部署全池推理成本为零。

## 7. 工件路径、hash payload 与状态

计划根为 `artifacts/research-v2/<study_id>/`。路径不是本轮已经产生的实验目录。

| 相对路径 | 定义/可读者 | 内容身份 payload |
|---|---|---|
| registration.json | StudyRegistration；调度/评测，selector仅获投影 | 源包/协议、数据链方法ref、完整cell/假设/配置矩阵、种子、决策、比较器/统计/阈值 |
| dataset/dataset-manifest.json | DatasetManifest；准备器，selector仅获D投影 | 原始来源及清理profile、canonical rows、标签、组件、split、许可摘要 |
| chains/<chain_id>/chain-manifest.json | ModelChain；准备器/评测，非selector完整输入 | 四版本权重/训练/推理身份、父链、实际随机实现、profile、密封handle |
| history/<chain_id>/history-view.json | HistoryView；selector可读 | 仅历史run/ID、D或DEV_SELECTOR、标签/特征/表示合同、有效转移、历史协变量合同 |
| pools/<chain_id>/pool-manifest.json | PoolManifest；selector可读 | history/data hash、f2正确规则、有序source_i摘要、标签/组件计数、无截断 |
| methods/<method_id>/method-manifest.json | MethodRegistration；selector可读当前方法 | origin/版本/commit、能力层、目标/配置/seed、差异/缺项范围 |
| suites/<cell_id>/suite-manifest.json | SuiteFreeze；冻结后只读 | 注册及全部选择依赖hash、cell配置、有序IDs/trace/fallback |
| freeze/matrix-freeze.json | FreezeMatrix；调度/评测 | registration/expectedcell/hypothesis/configuration hash、排序的全部cell引用及已批准缺项 |
| evaluations/<evaluation_id>/evaluation-result.json | EvaluationResult；评测器后产生 | matrix/registration/target run/分母/各cell计分、成本/访问审计hash及限制 |
| costs/cost-ledger.jsonl | 每行 CostLedger；追加事件 | 实测事件/attempt/phase/account、资源/调用次数、缓存、前事件hash |
| bundles/<bundle_id>/bundle-manifest.json | 未来只读ViewBundle；本草案未定义机器shape | 由已核验工件的发布投影生成，不能反向喂selector |
| events/events.jsonl | 追加状态/访问事件；详见04 | event序号、时刻、前eventhash、actor/attempt/输入输出hash、状态转换 |

这里 `CJ` 为 UTF-8、对象键排序、无无意义空白、禁止 NaN/Infinity、保留数组顺序的 canonical JSON。hash 为小写 SHA256。行数组先按 source_i 字节排序；label_vocab 按 UTF-8 字节排序；suite IDs保留选择顺序；矩阵cell按 cell_id 排序。raw 文件另按真实原始字节计算 hash，不能把 raw_sha256 当 canonical_rows_sha256。

`ArtifactRef.file_sha256`核对文件实际字节，`ArtifactRef.content_sha256`核对该种工件冻结的语义payload，两者不可混用。manifest的创建时刻等操作元数据可能使文件字节hash不同但语义hash相同；验证器两项都复算。普通不另定义语义payload的二进制/JSONL数据对象可约定两项均为实际字节摘要，并在media/type合同中明确。只核对语义摘要不能声称文件未被任何改动。

通用 `content_sha256` 的 payload 包含表中语义字段及 schema_version/artifact_kind/protocol/fixture、hash_payload_version和producer；排除 artifact_id、study_id、created_at、content_sha256 自身、状态、完成/冻结/解封时间等操作元数据。registration_identity 是显式配置身份，必须保留；run_id/attempt_id 在 PredictionRun/CostLedger 中是执行身份，也必须保留在对应 payload，不能因通用排除规则丢掉。任意对象仅允许按已冻结的 artifact-kind payload版本计算，不能由客户端自由决定排除字段。

`evaluation_data_sha256=SHA256(CJ({canonical_rows_sha256,labelset_sha256,component_manifest_sha256,component_assignment_sha256,cleaning_profile_sha256,identity_protocol}))`，排除人类名称/URL/UUID但保留真正影响样本、清理、组件及角色的字段。复制study UUID或改来源名称不能变成独立保留证据；读取日志和研究者历史认知也不能靠内容hash洗掉。

共同字段为 schema_version=`research-v2-draft1`、artifact_kind、artifact_id、study_id、created_at、fixture、protocol、content_sha256、hash_payload_version及producer。ProducerIdentity保存实际git commit、依赖锁、运行环境和命令配置hash；没有真实产物时不编造这些值。state取各工件定义的有限枚举。PREPARED仅用于已有所需实际输入的准备工件，不能用全0/随机hash代替尚未生成产物。READY/FROZEN/SUCCEEDED/EVALUATED必须有实际hash。正式研究运行要求 protocol_state=FROZEN；fixture/dev 可使用DRAFT，但对外不得称正式结果。

Study 当前状态由追加 events 投影：REGISTERED→DATA_READY→HISTORY_READY→SELECTING→SUITES_FROZEN→EVALUATING→EVALUATED→PUBLISHED。UNSEALED是矩阵冻结之后的审计事件，不是允许继续调参的阶段。失败保留attempt和输出，恢复必须同输入/协议/配置hash；有变更就建立新谱系，不能重写已冻结Suite或Matrix。时间先后只是证据的一部分，仍须验证事件顺序、输入身份和实际访问。

## 8. 评价与成本记录

EvaluationResult仅由evaluator在本comparison_scope的完整FreezeMatrix后生成：主比较在这时首次解封完整f3；全池增强已经按D15授权取得目标输入，评价只读取同一目标身份，不再声称首次保留。所有cell使用相同P、参考f2、目标f3和R*；先严格验证目标预测完整覆盖P，再计分。Recall检出数/|R*|，Precision检出数/actual size，Enrichment为Precision除P全池翻转率；零分母为null＋明确NA原因，不能写0来暗示效果差或好。

历史未见错误草案为 `R*` 中 H0=H1=0 的行；修复后复发为 H0=1、f2正确且f3错误的行。两者互斥，在两次相邻历史条件下覆盖未来错误；**D06/D09要求在正式注册中确认该口径**。Risk-LR 的逐转移训练与该最终分组不是同一时间标签。EvaluationResult保存每组detected/denominator/recall，不用一个主Recall掩盖持续历史风险与新错误的差异。

CostLedger 每行一个不可变事件，按 event_id/attempt_id 防重复；测量缺失写NOT_MEASURED和null，不填0。必须区分 sample_executions 与 unique_sample_count，实际请求或执行ID的摘要用于目标探测与套件重叠时去重，不能既复用缓存又重复记新调用。训练、表示、历史全池、参考分数、风险建模、选择、梯度/PCA、目标probe、B条推理、研究全池金标准和滚动refresh分别记录。

`ESTIMATED / NOT_MEASURED / FAILED_PARTIAL`必须有measurement_note说明依据、缺测或中断。执行次数若未知也为null；预算门禁所需调用次数不完整时，应标成本/预算证据不足，不能用null当0放行。已知不涉及某类资源可以记录真实0，并与未知区分。

复用历史的一次更新账为 T_select+T_probe+T_infer(B)，从零账另加T_build；研究用完整f3金标准列RESEARCH_ONLY，不能隐去但不混作部署每次B条成本。历史refresh列ROLLING_REFRESH，本研究不自动支持免费无限滚动。具体汇总规则及实测单位见04；仅由B/n不能推导token、秒数或费用。

## 9. SQLite概念表映射，不是现有迁移

下列是将来 `lab/` 离线实现的最小表manifest；现有 Demo SQLite 继续原样运行，不新增这些表。manifest文件是证据主体，SQLite是可重建索引，不是另一套可手改统计事实。

| 计划表 | 主键/唯一性与绑定 | 对应shape |
|---|---|---|
| research_studies | study_id；registration_sha256、projected_state、last_event_seq；冻结注册只读 | StudyRegistration＋events投影 |
| research_artifacts | artifact_id；唯一real_path/content_sha256；kind/schema_version/sealed/read_tier | 11种artifact header/ArtifactRef |
| research_prediction_runs | run_id；chain_id/slot/scope/identity/attempt/coverage；SUCCEEDED不可补行 | PredictionRun |
| research_cells | cell_id；唯一registration/chain/method/config/tier/budget/seed；预登记required状态 | SelectionCell |
| research_suites | cell_id唯一；suite_sha256/manifest_path；FROZEN不可改 | SuiteFreeze |
| research_matrix_freezes | registration_sha256唯一；matrix_sha256/expectedcellset；缺required cell拒绝 | FreezeMatrix |
| research_evaluations | evaluation_id；matrix_sha256/target_runset/结果sha；引用已冻结矩阵 | EvaluationResult |
| research_cost_events | event_id唯一；ledger_id/attempt/phase/account/prevhash；仅追加 | CostLedger一行 |
| research_events | study_id＋event_seq唯一；prevhash/attempt/actor/transition/artifacthash；仅追加 | 04定义的事件记录 |

以上表的跨工件约束、外键、原子发布、真实路径隔离和失败恢复要由06/07的实施测试证明。JSON Schema只校验形状和部分条件：不能证明SHA256真实、概率和为1、P确为f2正确、矩阵真的完整、时间未伪造、seed独立、代码没有偷读f3，或研究者没有看过目标后改方法。未实现这些检查前，本合同仍是可审查草案，不能据此报告科研结论。
