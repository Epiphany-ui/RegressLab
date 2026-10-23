# v2 离线工作流、冻结与成本

状态：**待实现的工程设计**。本文依据不可变的[算法原案](../../research/v2/source/03-algorithm-spec.md)和[实验原案](../../research/v2/source/04-experiment-protocol.md)细化执行边界，不记录真实方法收益。文中的研究CLI、状态机、访问检查和工件发布器均为 `PLANNED_NOT_IMPLEMENTED`；现有 CLI 只有本地描述性 Demo 与 doctor。未来实现的验收见[06](06-validation-plan.md)，开发顺序见[07](07-implementation-plan.md)。

## 1. 当前、核心计划与扩展

| 能力 | 状态 | 本轮处理 |
|---|---|---|
| SQLite＋FastAPI＋Vue 的导入、D 成对指标、案例、历史、JSON/HTML | 当前已有 | 复用为证据浏览器，保留原 Demo 身份与结果 |
| 四版本链、历史风险、统一选择器、矩阵冻结、目标解封和两本成本账 | 计划核心 | 离线 Python 实验优先，实现后才可宣称支持 |
| SliceLine 或 DivExplorer 的至少一个可安装适配核查 | 计划核心 | 固定版本、小例核算、同信息条件比较；不是完整发现器竞赛 |
| CPU 方向梯度参考 | 计划核心 | 独立白盒访问层，不伪装成标签访问方法 |
| 神经模型迁移 | 受 G0 资源门约束的计划 | CPU 主比较之后进入；GPU 初始上限20小时，不保证3条链可行 |
| C 净下降确认、更多群体发现器、语义表示、目标探测方法 | 可选扩展 | 各自登记；不能为 HGC 失败临时增加有利配置 |
| PostgreSQL、认证、多 Worker、Ollama/API、网页训练 | 暂缓 | 不作为研究核心完成的依赖 |

## 2. 两条隔离轴

样本轴保留原始 TRAIN；DEV 按组件划为 `DEV_MODEL` 与 `DEV_SELECTOR`，分别用于任务模型开发和选择器开发。组件50/50是工程初始建议，具体算法、命名空间、seed及实际类别支持量须登记。官方 TEST 的 v2 初始方案为 D/C/A=80/10/10；组件整体划分，不能按行重新抽签。开发阶段检查数量可行性，正式 f3 解封后不得调整。

现有 Demo 的 `split-v1` 50/25/25属于旧协议，保持原样；v2 使用独立协议标识与工件，禁止覆盖原数据角色。相同数据重新命名、换 UUID 或换来源说明不恢复盲态。曾看过某正式 f3 结果的批次只能登记为开发或探索。

版本轴为 `f0 → f1 → f2 → f3`。历史视图只有 D 的 gold、文本/允许特征及 f0/f1/f2 记录。`P={i∈D:f2(x_i)=gold_i}`，所有方法使用同一个 P，评价分母为 `R*={i∈P:f3(x_i)≠gold_i}`，不使用 A 中错误替代。f1→f2 在 P 内的负向翻转必为零；PastFlip 使用任意过去转移，不能只取最近一次。Risk-LR 的训练标签来自开发历史，特征必须截止被预测转移之前。

开发链可评价其开发目标，但不复用为正式保留目标。正式与开发的训练实现、抽样/优化种子、家族分工和目标身份预登记；同一训练 run 的四个检查点仍是一条相关链。

## 3. 信息访问层与展示表

| 访问层 | 选择前允许的信息 | 目标 f3 的访问 | 必须独立报告 |
|---|---|---|---|
| `HISTORY_LABEL_ONLY` | D gold、固定文本表示、f0—f2 标签/正确性与过去翻转 | 无参数、梯度、概率、标签或探测 | 主标签访问表 |
| `REFERENCE_SCORES` | 上述信息＋定义明确的 f2 类别分数；历史分数可另登记 | 无 f3 访问 | 参考分数表；分数获取成本 |
| `TARGET_WHITEBOX` | 已登记历史信息＋白盒 f3 权重差 | 仅声明的参数读取；不运行 f3 全池推理 | Grad-PD/GBV-PD 白盒表；梯度、PCA与提取成本 |
| `TARGET_PROBE` | 声明的信息＋有预算的目标探测 | 有限探测，计入总执行预算 | 增强探测表；次数、重叠与总预算 |
| `TARGET_FULL_POOL` | 已执行完整目标池的标签/分数 | f3全P预测 | 全池增强表；实际n次支出，不能冒称B<n执行预算 |

`HISTORY_LABEL_ONLY` 选择进程的输入包不包含 f3 路径，工作目录/允许工件根不包含目标目录。`TARGET_WHITEBOX` 与 `TARGET_PROBE` 使用独立上下文和进程，不能把获得的信息写回主标签方法的风险、锚点或选择文件。仅有 hash 和访问日志不能证明操作者从未私下查看目标；已知曝光须记录，不能以日志替代研究诚信。

`Ref-Uncertainty` 分别实现 ref-maxprob、ref-margin、ref-entropy、ref-deepgini，使用 f2 合法类别分布。生成标签的首个 token 概率不能当完整60类概率；采用分类头或完整标签序列似然及其归一化定义须在模型开发阶段冻结。若分数确实不可得，在解封前登记 `UNAVAILABLE`、理由与受限比较范围；不能把未实现或运行失败改成不可用。

主表至少登记 Random、Stratified、PastFlip、四种参考不确定性、KCenter、Facility、Risk-Top、Risk-LR、Behavior-Anchor、Legacy-adapt、HGC；CPU Grad-PD 另表且仍属核心。Behavior-Anchor、Legacy-adapt及文本适配方法明确 `method_origin`，不能把启发或适配标成原样复现。主比较器在开发结果中从非 HGC 方法选定，正式阶段不得挑弱对手。

## 4. 工件与固定发布位置

计划以本地 `artifacts/research-v2/<study_id>/` 为研究工件根，路径由受信 CLI 生成；HTTP 不接受输出路径或命令。原始下载目录与训练依赖另行管理，下载/许可/文件 hash 均进入来源清单。

| 工件相对路径 | 含义和可见边界 |
|---|---|
| `registration.json` | 数据/链/方法、访问层、预算/种子、主指标、比较器、开发轮和接受规则 |
| `dataset/dataset-manifest.json` | 来源版本、许可、原始/规范化文件 hash、排除清单、组件与分区计数 |
| `chains/<chain_id>/chain-manifest.json` | 四个真实版本的训练来源、抽样/优化实现、权重/推理身份；目标输出位置不传 selector |
| `history/<chain_id>/history-view.json` | 仅 f0—f2 的 D 历史及允许依赖引用 |
| `pools/<chain_id>/pool-manifest.json` | 有序 P、gold/参考正确性、组件、特征/向量/锚点指纹 |
| `methods/<method_id>/method-manifest.json` | 论文/代码版本、原样/重实现/适配说明、访问要求、配置与运行资格 |
| `suites/<cell_id>/suite-manifest.json` | 一个方法×配置×链×预算×seed的有序选择、理由、实际数量和依赖hash；前缀资格依ranking_policy |
| `freeze/matrix-freeze.json` | 预登记全部必需单元、全部 suite 引用及 hash 的完整冻结矩阵 |
| `evaluations/<evaluation_id>/evaluation-result.json` | 同一 P 上的解封评价、分母、NA、各预算及各方法结果 |
| `costs/cost-ledger.jsonl`、`events/events.jsonl` | 只追加的成本与状态/访问事件，含 attempt 和前序关联 |
| `bundles/<bundle_id>/bundle-manifest.json` | 验证通过的只读 UI 证据包，排除选择前的目标与 C/A 逐例数据 |

正式目标预测保存在 selector 允许根之外的 `var/sealed-targets/<study_id>/<chain_id>/`，由evaluator解析。可以预先训练并登记f3权重；主方法仍不能读取其内容。完整金标准优先在主矩阵冻结后生成；若预先生成密封缓存，登记生成者、时间、hash、访问记录，并保证主方法及研究决策者未读取；这不等于允许提前解封。未生成时不得编造预测hash。声明的白盒参数和有限探测使用独立能力，不由此获得全池缓存访问。

### 全池目标基线的独立分支（D15）

主登记/矩阵使用`comparison_scope=CORE_PRE_TARGET`，其中没有TARGET_FULL_POOL。标签/参考分数主方法、声明的白盒及可选有限探测先完成整个预登记矩阵；此后才授权评测器解封完整f3。全池增强方法的配置在看目标前写入提案，使用独立`ENHANCED_TARGET_ACCESS`登记并引用实际`parent_core_freeze_sha256`。增强registration自身冻结后可取得全池输入，再运行增强选择、冻结自己的矩阵并评价。既不能要求这些方法在获得必要输入之前已选出全部套件，也不能在看到结果后改增强配置或回写主方法。

授权字段分别为`ONLY_AFTER_FREEZE_MATRIX`和`AFTER_PARENT_CORE_FREEZE_AND_OWN_REGISTRATION`；FreezeMatrix的`undeclared_target_access_before_freeze=false`检查未声明访问，不把已登记白盒/有限探测误判成主方法泄漏。增强分支不作为最小核心必做，启用时仍要完成其自己的完整矩阵和独立费用表。

每个 JSON 的规范化、数组排序和 hash 负载以领域合同为准；文件 hash 对实际字节重算。工件记录 schema/protocol、代码 commit、依赖锁、环境、父清单和输入 hash。写入过程为 attempt 临时目录→格式/语义/覆盖/hash验证→同文件系统原子发布→追加事件。已发布路径禁止覆盖；同一逻辑单元重复执行只能产生新 attempt，内容一致才允许复用引用，不能覆盖旧时间或成本。

## 5. 未来 CLI 与状态 DAG

以下均为**计划命令，当前不可执行（PLANNED_NOT_IMPLEMENTED）**。研究编排入口计划为独立`lab/`包的`python -m regresslab_lab.cli`，表中除训练/预测外省略此前缀；训练/推理由独立`experiments/`包的`python -m regresslab_experiments.cli`承担，不改现有`regresslab.cli demo/doctor`。初始 fixture/development registration 可含显式 `DRAFT` 选项；正式登记必须引用真实已准备工件并完成所有待决字段。训练/数据准备按独立冻结的 profile 进行，正式研究登记不倒填不存在的权重 hash。正式登记以新的 study_id 引用准备阶段工件，保留`parent_registration_sha256`和development/provisional父记录，不能覆盖原registration。正式study依次重验引用到HISTORY_READY，再允许SELECTING；state由事件投影，不能为了记录阶段而重写registration。

```text
准备工作：来源审计 → 任务模型开发 → 真实四版CPU链 → f0-f2历史缓存
                                              ↓
REGISTERED → DATA_READY → HISTORY_READY → SELECTING → SUITES_FROZEN
                                                      ↓
                      PUBLISHED ← EVALUATED ← EVALUATING
                                      ↑          │
                                      └─同一评价session的受控恢复
```

`UNSEALED` 是发生在 `SUITES_FROZEN` 后的审计事件，不是可回到选样阶段的状态。失败 attempt 标记 `FAILED` 或 `INTERRUPTED` 并记录停在何处；study 的已提交阶段不回退，不能删除冻结或解封事件再继续调参。

| 计划命令 | 输入与输出 | 进入下一阶段的条件 |
|---|---|---|
| `audit-data --profile <file> --output <prep-dir>` | 本地原始文件→审计、排除清单、规范化数据与 dataset manifest | 来源齐全、无残余跨分区/标签冲突；不自动下载执行代码 |
| `prepare-dev --dataset <manifest> --profile <file>` | DEV_MODEL/DEV_SELECTOR组件清单 | 比例、seed、用途明确且不重叠 |
| `python -m regresslab_experiments.cli train-cpu --profile <file> --dataset <manifest>` | TRAIN-only四版真实训练→chain manifest | 全类别、独立训练实现和保存恢复证据 |
| `python -m regresslab_experiments.cli predict-history --chain <manifest> --data <manifest>` | f0—f2固定范围预测→合法单run产物 | 输入无gold泄漏、完整覆盖、无静默截断/补错 |
| `register --registration <file> --purpose development\|formal` | 校验完整清单，创建 REGISTERED | 正式接受规则、全单元矩阵、访问例外均确定 |
| `verify-data --study <id>` | 重算所引用数据hash→DATA_READY | 角色协议/来源/排除记录一致 |
| `build-history --study <id>` | 允许历史→P、群体、表示、锚点→HISTORY_READY | 只有D与f0-f2；依赖工件封存 |
| `select --study <id>` | 运行预登记矩阵→各suite manifest | 选择器只能访问本层允许的输入；记录完整实际成本 |
| `freeze --study <id>` | 校验全矩阵→matrix-freeze→SUITES_FROZEN | 必需单元齐全、配置一致、所有hash重算通过 |
| `evaluate --study <id>` | 受信evaluator读取封存目标→EVALUATING/EVALUATED | 主矩阵先于完整目标解封；增强分支先核验父矩阵及自身冻结，目标覆盖同一P |
| `aggregate --study <id>` | 链内seed汇总、跨链配对结果与成本 | NA/缺项保留，统计家族与比较器未变 |
| `publish-view --study <id>` | 公开字段白名单→bundle→PUBLISHED | 无C/A逐例/私有目标路径；证据模式与来源完整 |
| `verify --study <id>`、`resume --study <id> --stage <name>` | 验证全部引用；仅恢复同输入同配置失败阶段 | 不重置访问资格、开发轮、成本或解封次数 |

冻结检查对预登记 expected cell set 做集合相等验证；不是“目前成功的文件全在就通过”。必需方法运行失败阻止冻结；只有目标访问前已批准的 `UNAVAILABLE` 例外可改变适用范围，并限制结论。B={20,50,100,200}、主B=100；实际 b=min(B,|P|)，n不足时多个名义预算映射同一 b，保留别名但只统计一次，不能制造重复实验。

HGC、Facility及具有固定排序/递增序列的已登记方法执行至最大实际预算，再取前缀；Stratified按每个预算计算最大余数配额，不要求不存在的前缀性质，其他预算相关方法也须在ranking_policy说明。HGC初值m=30、k=3、λ=0.5，最多30风险组、至多256锚点；无有效风险时记录`fallback=NO_POSITIVE_RISK_REPRESENTATION_ONLY`并使用F，不除零或伪造风险。≤6个λ/m核心配置、≤2轮开发；λ=0/1和k=1是单列机制消融，不做笛卡尔扩张。HGC的代理目标近似界不等于未来Recall保证。

### 中断与解封恢复

选择阶段只复用已验证且同依赖hash的 cell；中断的新 attempt 不能悄悄替换已冻结单元。正式 evaluate 创建唯一评价 session，并先追加 `UNSEALED` 事件；若中断，可在同冻结矩阵、同目标manifest、同session内恢复未完成计算，全部attempt成本累计。不能另开“未见”session再试方法。已部分查看目标结果亦记曝光，禁止恢复选择或改变注册矩阵。

目标输出非法/缺失与分类错误分开：完整合法之前不发布常规 Recall/Precision；失败输出不能删行、当错误或补采样。生成不稳定需记录执行问题及降级范围，不能将其伪装为权重变化的确定结果。不要把已有Demo中的C确认409改成v2实验入口。

## 6. 两本成本账与研究审计支出

每条成本事件至少记录 study/chain/method/cell、stage、attempt、访问层、开始/结束UTC、wall seconds、CPU/GPU seconds、峰值RSS/显存、输入/输出条数与字节、目标执行次数、token计数（适用时）、cache状态、artifact hash和费用来源。没有测量的量为null并说明原因，不用0代替未知。不把不同硬件的时间直接相加作公平加速比。

其中当前Schema的最低字段为CostLedger定义；访问层由cell/method关联复核，尚未定义的字节吞吐扩展在实现时版本化加入，不能把文档扩展清单当成现有字段。`MEASURED / ESTIMATED / NOT_MEASURED / FAILED_PARTIAL`分别展示；估计值不得覆盖实测。`TARGET_FULL_METHOD_ACCESS`属于增强方法的PER_UNSEEN_UPDATE支出，`TARGET_FULL_EVALUATION`属于RESEARCH_ONLY。若共享同一次物理全池执行，事件只记一次，各账通过明确分摊/反事实部署估计引用，不重复计费，更不把缓存查表称为零成本目标推理。

| 事件 | 已有历史复用账 | 从零建库账 | 研究审计单列 |
|---|---|---|---|
| 获取/清理数据、许可、训练、f0-f2全池推理 | 列为已存在的前提与沉没成本，不隐藏 | 全部计入T_build | 如为研究额外准备再给实测总量 |
| 文本表示、群体风险、Risk-LR、锚点/相似度 | 本次新增计入T_select；已封存复用须明确边界 | 加上构建成本，避免重复计算共享产物 | 多方法共享计算给独占与共享分摊两列 |
| f2类别分数、历史行为缓存 | 缓存缺失时实际补算；存在时标明先决条件 | 全量计入 | 不能把分数层当作免费标签层 |
| Grad-PD参数提取、旧梯度、PCA | 方法需要的增量预处理全部计入 | 未有缓存时全部计入 | 白盒访问单列，参数读取不等于目标推理 |
| 目标探测、选择后目标推理 | T_probe＋T_infer(实际执行) | 同左 | 探测重复执行也记执行事件 |
| 为求真实R*的f3全P预测/金标准 | 不伪装为部署节约，单列说明 | 不隐藏进建库前提 | 全量记录T_gold及实际支出 |
| 失败/中断、验证、导出 | 报实际attempt总额，另列成功路径成本 | 同左 | 不以失败被排除而删除支出 |

一次未见相邻更新的历史复用成本为 `T_select + T_probe + T_infer(b)`；从零成本为 `T_build + T_select + T_probe + T_infer(b)`。与相同P、硬件/批量和合法输出合同下的 `T_infer(n)` 比较。研究总账另含全部方法、开发尝试、训练和 `T_gold`；同一次物理推理可以由账目引用分摊，但不能既被标成未发生又计作节省。缓存查表耗时不是模型推理耗时。

目标探测方法约束以执行事件核算：`probe_calls + selected_infer_calls ≤ B_total`。本草案初始适配要求探测为P内唯一ID、每例一次、全部探测ID纳入最终套件，后续只补足剩余额度；因此套件仍可取min(B,|P|)，已有探测响应复用但不可再次隐含执行。记录distinct目标样本数、重叠数和实际调用数；重复/失败费用照记，不能用去重后的ID掩盖超预算。其他探测机制需新合同批准。全池f3概率方法记完整池访问和实际支出，不能再声称遵守B<n的执行预算；放在增强访问表。

样本预算相同不表示token/秒/费用相同；逐例文本长度、批量与模型环境记录后给出实测曲线。API不是主实验，无需估算未来厂商价格。CPU推理过快导致选择比全测更贵是允许的结果。

只执行f3的B条，不能免费获得下一次f3→f4的完整当前正确池和历史群体风险。若探索连续滚动，必须新增协议并把每次 `T_refresh` 全池补测逐笔加入；本轮不推算未经测量的多轮回本次数。

## 7. 开发与结论出口

G0/G1/G2/G3的检查材料和判定见[验证计划](06-validation-plan.md)。来源未给出的聚类细节、DEV比例、训练配方、开发稳定性/成本容限与统计接受规则，先写成带版本的工程草案；正式注册不得留未决字段。修改草案不等于已经选定最佳配置；每轮完整保留失败和成本。

G2失败可停止HGC调参并转比较研究。G3允许支持局部有效、接近但成本/访问有折中、证据不足或负结果；没有任何状态自动产生“胜出”“安全”或“统计等效”结论。
