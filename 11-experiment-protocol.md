# 研究问题、真实更新链与实验协议

文档版本1.3，2026-10-22。全部为拟实施协议，尚未下载数据、训练模型、测得显存或效果。离线脚本产生训练/预测产物，产品负责导入、诊断、套件和重放；没有网页大模型训练平台。

## 1. 论文定位与证据层级

论文为应用开发类：完整系统、正确的实现、可追踪的实验和边界是主要交付。使用已有LoRA产生实验版本，不声称提出微调算法；套件选择是待验证的工程启发式，不承诺发表或优于基线。人工翻标签/伪造预测仅作工程夹具，不能证明自然退化或算法效果。[S01][S15]

- RQ1：在同一历史权重更新中，成对净退化目标相对新版错误目标等分组方法，得到哪些可独立确认的退化分组？报告数量、效应、支持和成本，不把确认数称真实缺陷召回率。
- RQ2：在相同候选池、预算和未用于选择的后续权重版本上，固定精选策略相对五基线是否提高未来负向翻转产出及冻结分组的检出比例？
- RQ3（统计仿真/辅助）：独立D/C和Holm的组合，在明确假设的零净退化仿真中如何影响误确认；真实数据中要付出多少功效/支持量代价？

最少主证据是一条真实小语言模型权重更新链，加一条逻辑回归重训练对照链；两条不同技术路线不等于两个独立重复。不强制不同参数规模/API全覆盖。若主语言模型训练不可行，不可悄悄改用提示词变化后仍保留“权重更新已验证”的结论：报告可行性限制，先保留系统和CPU对照，重新与导师确认论文证据范围。

## 2. 数据、权重版本与更新来源

主数据MASSIVE1.1 zh-CN；en-US为预登记可选扩展，单独报告。使用官方TRAIN/DEV/TEST和03的component去重/划分；TRAIN只训练，DEV只做资源试训、训练设置和稳定性预实验，TEST的D/C/A不参与模型或策略调参。归一化导致跨分区重复/冲突的数量尚未实测；如启用03的严格转换清洗，须预先固定“移除全部相关冲突component”政策、记录完整排除清单/hash/各标签与分区剩余量，并明确结果是清洗子集，不冒充官方全量。不能按错误或退化结果挑选排除组件。清洗政策和特征目录在正式结果读取前冻结。所有预测输入不得含该样本金标准；标签全集/说明可提供，few-shot例子仅来自TRAIN。公开数据预训练污染不能排除，不宣称模型从未见过样本。[S02][S03][S09]

### 2.1 主链：真实小语言模型训练更新

拟以固定revision的公开Qwen3-0.6B权重，用Transformers/PEFT LoRA仅在TRAIN训练；按预登记optimizer step保存三个checkpoint为v1、v2、v3。具体训练配方、完整序列长度检查、产物、父子关系和资源降级规则由[19](19-model-version-protocol.md)唯一规定。6GB显存可行性未测，1.7B仅为实测后可选扩展，不能预先承诺。

v1→v2是历史修改，v3是预留未来版本。这是可复现的维护更新模拟，不声称有真实生产部署历史。继续训练是优化尝试，不要求平均准确率提升，更不保证存在退化。v1/v2/v3来自同一训练run，是一个相关更新链，不是三个独立训练实验。不得根据D/C/A分数挑checkpoint或只保留“平均更好且局部更差”的链；预定checkpoint即使无退化也保留。

权重对比较固定同一推理后端、tokenizer、精度/量化、提示词、标签词表/映射、解码及重试策略。ModelVersion.content_sha256是应用版本指纹；另核对不同weights_sha256、相同inference_config_sha256，记录change_type=TRAINING_UPDATE、父版本与provenance_status。PRECOMPUTED主路径从离线脚本导入预测及训练/推理manifest；声明文件通过格式校验不等于服务端已验证训练真实性。不得把Transformers和Ollama后端差异混作纯权重效果；LoRA转Ollama只是选做工程扩展。

### 2.2 CPU对照与可选服务参照

逻辑回归保留为真实重训练对照：固定字符TF-IDF配置、C=1、seed42，TRAIN采用嵌套分层比例0.5→0.8→1.0，每次仅在相应子集重新拟合完整Pipeline。确切子集与产物hash见19。标签缺失/训练不收敛须报告，不以测试准确率重选参数。它可以调参，但本主链固定参数、只改训练数据量，以解释修改来源。[S09]

原生Ollama已安装模型推理用于系统完整功能与可选模型替换示例，不代替主链微调证据。API为可选的应用配置/服务参照；改提示词或温度不算改权重，API调用方式也不等于闭源或已知模型规模。厂商可能更新同名后端；无法冻结时必须明确。没有API仍能交付P0；不强制为显得全面增加花费。

跨规模扩展只能回答所测模型/训练配方下的差异。不同架构、训练数据、量化或服务后端都可能混杂；不能把逻辑回归、不同家族和参数未知API排成参数量轴后声称大小的因果效果。

## 3. 资源与推理稳定性前置门

先在DEV完成全量标签提示词长度、合法输出、训练显存/耗时和推理噪声检查。完整序列包括类别说明、输入、输出/控制token；不能只测短句后截掉类别或答案。若预设1024不足，必须在正式登记前调整配方/长度并重新试训，不得按TEST是否可预测筛选样本。

正式LLM独立确认的门：每版本取相同100条固定DEV样本，各推理3次；100%合法且每样本三次解析标签完全一致。ID以SHA256('stability-v1|42|'+sample_id)升序取前100，再按sample_id解同分；DEV少于100时LLM不能进入CONFIRMATORY，不能把重复行补足100。记录原始输出和运行manifest；重复推理不是新增独立样本。温度0/greedy不保证所有硬件/运行时绝对确定。先尝试固定确定性实现或可行的CPU推理，变更后重新做DEV门。

通过门、冻结同一推理配置且满足来源要求，才可登记evidence_mode=CONFIRMATORY。零观察差异只是有限DEV证据，正式运行仍记录后端与异常。门失败、缺失或持续有输出变异则DESCRIPTIVE_ONLY：系统可处理一次冻结实现的预测、展示计数与候选，Slice保持PROPOSED、confirmation=null，confirm请求409，摘要INCONCLUSIVE/EVIDENCE_NOT_CONFIRMABLE；不读取C作独立显著性确认，不将波动解释为权重导致的已确认退化。研究随机预测器的期望退化需额外重复抽样/层级协议，不在P0补做临时检验。

每个正式scope必须100%匹配合法预测才进入成对能力指标；导入/推理失败整体拒绝该比较并单列执行覆盖诊断。重试次数和采用“第几个合法结果”在DEV前固定，不能从多次输出里选对的一个；也不能删去强模型格式错误来制造100%覆盖。真实结果不足时说明无法完成该研究比较。

## 4. 预登记、盲态与复用

默认路径是评价固定初版selector，不做算法调整。资源试验后、首次读取正式D历史成对结果之前，登记数据/切分、全部模型链和checkpoint、训练run/seed、推理配置、稳定性记录、方法/预算/seed、候选特征、阈值、指标及停止规则。具体运行hash未知时保持“未运行”，不能写猜测值。

历史只允许v1/v2的D结果及一次冻结家族的C确认结论进入套件选择。先冻结候选和选择实现，再生成全部suite，记录有序ID/hash与时间。此后才允许v3的DEV稳定性推理和正式D/A预测。v3稳定性失败只降级未来权重效果主张，不改训练、推理后端、提示词、选择器或替换目标；历史合格RQ1与未来RQ2分开记录。v3训练文件可提前存在，但未来预测/分数不得提前查看；操作人访问日志与文件权限用于可审查的盲态，不宣称单人场景有第三方保密保证。若不慎查看，原正式run改为EXPLORATORY；不能换ID恢复盲态。

A只在方法与suite冻结后最终一次读取；问题排查可以停止并报告，但不能用A改完策略再称同份A独立。产品演示用独立演示语料/版本，避免先在界面看完研究C。复制dataset/model/run ID不构成新证据。

ConfirmationUse/lab registry以(evaluation_data_sha256,old_model_content_hash,new_model_content_hash)占用；evaluation_data_sha256是canonical_rows_sha256、labelset_sha256、split_manifest_sha256组成的canonical JSON摘要，不含dataset UUID、source、名称、许可或版本描述。重复推理run_id、复制数据并改source/version都不会重置C。该键只能防止完全相同内容的直接复用，不能自动识别人为删行/改切分的适应性窥视；研究登记还必须追踪数据来源与父版本，读取正式结果后改变清洗/切分只能标探索，不能声称重新获得盲测。旧新model_content_hash均指应用内容指纹，预测snapshot hash与推理配置另登记。每内容对/冻结家族的Holm只控制本家族；不声称多条更新链、多个语言或长期反复实验合计仍为5%。默认跨链结果为描述性比较；若另提跨链正式显著性主张，须在读取结果前定义更大的检验家族与修正协议，否则不得补写总体显著性。

## 5. 分组方法与一次共同确认

所有方法使用同一历史模型对、D、输入特征、最大深度2、D支持30、最多20组、去重与稳定同分规则。默认表面特征目录可能对单语言60意图问题区分力很弱，支持40和Holm也可能使确认数为0；这不是降低阈值或在TEST临时加金标准特征的理由。

1. 预定义单字段分组。枚举现有目录所有非空feature==value，以与本方法相同的D净下降、支持筛选/排名/去重取最多20；不搜索合取。
2. 新版错误驱动的同一枚举器。目标为new_error_rate，D支持30、新版错误至少1；按new_error_count/sqrt(n)降序、n降序、canonical谓词排序，其余深度/去重相同。不额外要求净退化，否则把成对目标偷偷加回基线。
3. 本设计成对净退化枚举器，按04。
4. SliceLine分别以新版error、negative_flip为目标运行。限制相同输入特征、深度、支持和最多20组，记录实现版本/参数与不能严格对齐的目标差异；若实现不兼容，在预登记前解决或明确未完成此强对照，不冒称已比较。[S04]
5. Deepchecks WeakSegmentsPerformance仅为预登记可选树分组对照，安装/接口不兼容时如实说明。[S05]

必做五配置：单字段、新版error、成对净退化、SliceLine error、SliceLine negative_flip；可选Deepchecks使之六配置。所有配置先只看D，按canonical谓词去重并冻结并集U；各配置最多20，所以U最多100/120组，不在去重后再次按C有利与否截断。只对完整U读取一次C、统一Holm，再把相同组结果映射回各方法。不同候选数造成的搜索预算差异和U共享修正的功效损失均报告。

单个P0 Analysis仍是一家族；上述比较属于独立LabComparisonRun，不冒充产品API资源。lab输出lab-1.3，登记全部配置、各自候选、union_hash及共同确认结果。registry和产品ConfirmationUse须互查；同内容对已读取C则拒绝主实验或标EXPLORATORY_REUSE，失败仅允许相同union_hash恢复。DESCRIPTIVE_ONLY可冻结U并展示D结果，但不消费C完成“确认”。

## 6. RQ1/RQ3的结果与统计限制

每历史更新链报告D候选数、C确认/支持不足数、净下降分布、组间重叠、搜索时间/RAM及数据规模。无完整真实缺陷目录，确认比例不是precision、未发现数不是false negative，不能说召回了全部问题。按04的component代表做确认，同一条语句多译文不增大独立样本量。[S07][S08]

RQ3采用独立统计仿真，不改真实gold：固定可计算类别特征、组件数和各组模型基础正确率；在零净差条件下令每组件b/c对称抽样，D/C独立生成，完整重复“D挖掘→冻结→C确认”至少1000次，记录任一误确认比例及二项区间。参数/seed、全部失败仿真先登记；可以增加多个零假设场景，但分别报告，不只留好看的场景。仿真下控制不能推广为业务安全认证。

无Holm、D/C混用、无最小支持门槛作为lab仿真消融，不能是产品开关。无支持消融只保留n>0的组，其余相应规则不变；混用消融以同份数据挖掘与检验，以显示选择偏差。真实数据C/A不足及检验功效降低同时报告，不把“少确认”自动当作“误报少”。

## 7. RQ2：冻结套件面对真正的未来权重

历史v1→v2生成全部suite后，评价预留v3。套件候选池固定为P={D中v1正确}，共同截断为P'；主未来方向是**v1→v3**。这衡量对当前基准的持续兼容性，不是相邻一步净优化率。辅助报告v2→v3相邻变化，但P'不是专为v2正确建的池；翻转数除以同一实际预算b，另列v2正确数量和条件率，不能混用分母。

五基线random/stratified/historical/coverage/diversity，加complete与ablate_history/ablate_diversity，共8方法；可选history_first为预登记第9项。定义、seed0—19、同分和共同向量器按[17](17-baselines-and-algorithm-evolution.md)。预算B={20,50,100,200}，实际b=min(B,|P'|)。所有selector共用相同C确认义务，不能让本方法有更多分组信息或更大候选池。种子产生选择随机性，不是训练重复。

- **逐例主辅助结果**：v1→v3未来负向翻转数/b、翻转绝对数、固定P'上的完整未来翻转数。因为P'均为v1正确，这里的suite分类错误与该方向负向翻转一致。池无未来翻转时，不存在可检出的目标；报告0与不足，不宣称安全。可另报告相对完整池产出率，但同方法/版本的分母必须相同。
- **预登记主指标**：冻结历史分组并集U在A上，按03同样的component代表算v1→v3；支持≥40且观察净下降≥0.05者记为“审计观察退化组”。所有selector共享此同一分母；某suite至少含一例该组的v1→v3负向翻转算检出，比例为检出数/观察组数。零组返回not_applicable，绝不返回100%。这里没有新的显著性确认，A门槛是描述性观察口径，不是真实缺陷金标准或总体覆盖率。U之外的新问题不在本指标覆盖范围。
- **其他结果**：标签/历史确认组义务覆盖与未覆盖、distinct component数、每预算的选择耗时/RAM、建库和后续推理成本。组重叠时各组计数不能相加当distinct失败数。

每链每预算先对选择seed求均值/范围，再展示每条链；固定方法只运行一个确定输出，不复制20次当20个实验。训练run/seed、同run checkpoint、未来版本、选择seed和样本组件是不同层级。最少一条LLM链加一条LR链时按技术路线分别描述，不进行“跨模型规模普遍有效”推断，不以它们算一个漂亮显著性p值。若后续有多条独立训练seed/run，仍报告共享数据/基础模型的相关性，链等权聚合只作清楚的摘要。

### 7.1 Lab独立预测闭环：A与完整P'不走产品接口

产品PredictionScope只有ROLES(D/C)与SUITE，不开放AUDIT角色或任意ID列表。未来P'全池/A审计由受信任的本地lab进程处理，不增加HTTP读取A、上传lab预测或导出任意路径能力。未来实现的CLI合同为：

```text
python -m regresslab.cli lab prediction-inputs --registration <registration.json> --target-model <model-version-id> --scope AUDIT|POOL --output <inputs.jsonl>
python -m regresslab_experiments.cli infer --manifest-kind lab --model-manifest <model.json> --run-manifest <lab-run-manifest.json> --inputs <inputs.jsonl> --output <predictions.jsonl>
python -m regresslab.cli lab prediction-validate --manifest <lab-run-manifest.json> --predictions <predictions.jsonl>
python -m regresslab.cli lab evaluate --registration <registration.json> --predictions <validated-lab-run-directory> --output <result-directory>
```

四个命令为待实现合同，尚无可执行产品代码。prediction-inputs验证预登记身份、允许的目标版本、固定evaluation_data_sha256和所有方法/预算/seed的suite有序hash已冻结；生成all_suites_freeze_sha256。未冻结、未来预测已提前访问、目标不在登记中或内容不符时拒绝。POOL严格取本次共同P'，不是某selector单独套件或临时筛选集；AUDIT严格取已冻结A。输入只含sample_id/text，标签词表来自冻结旁路配置，不含逐例gold。scope输入导出及预测读取均记访问日志；同一最终审计session可以为预登记基准/未来模型生成各自run，不允许交互查看A的gold或按单个结果反复审计。A标签仅在全部未来预测就绪后由最终evaluate一次读取。

lab预测行沿用run_id、sample_id、prediction_label、raw_response(≤32768)及可选latency_ms，不含gold；每scope完整合法一一匹配才SUCCEEDED。单独的[LabPredictionRunManifest](contracts/lab-prediction-run.schema.json)为schema_version=lab-1.3、manifest_kind=LAB_ONLY，scope.kind为LAB_AUDIT/LAB_POOL；绑定registration/design/evaluation/labelset、应用/真实权重/推理配置指纹、expected_ids_sha256、expected_count、输入/输出JSONL摘要、run_id、全部suite冻结摘要、证据模式/稳定性/来源与时间。PREPARED时输出hash为null，成功后必须补真实hash/完整coverage；JSON Schema不能表达的valid=expected、ID集合相等、时间先后、hash重算与相同run_id由validator执行。LAB_POOL另绑定pool_sha256；LAB_AUDIT没有pool hash。manifest不得冒充产品scope_hash，product_import_allowed恒false，HTTP导入明确拒绝。

历史v1/v2的D预测可供lab核对共同池；A的v1基准及v3未来预测均在此最终session产生。结果仅写lab目录供冻结评价器消费，不回填成产品PredictionSet或Report。研究全池和A预测成本完整计入；另外估计真实使用suite时边际模型调用量，不把全池预计算后的文件查表耗时当成实际节省。

## 8. 成本、停止规则与Go/No-Go

成本分列：数据获取/清洗、训练与checkpoint储存、DEV重复稳定性推理、历史D+C建库推理、选择、未来每版本suite推理、未来P'/A完整审计推理、可选API。实验时为评价所有方法可能预计算全量未来预测，这笔审计成本必须计入研究总成本；只有之后真实部署按suite运行时才讨论边际节省，不能把文件查表时间冒充模型推理速度。

本地记录GPU确切型号与6GB可用显存、CPU/RAM、依赖、batch/context/精度、墙钟、峰值RAM/显存、预测量及失败；不得把模型下载体积当显存峰值。API记录真实模型标识/时间/用量/失败重试，费用按运行当天官方价格，不沿用2026价格预测2027。[S14]

实施前两周先做DEV小实验：完整提示词、32step试训、三checkpoint可产生、合法输出/稳定性门、墙钟和显存均记录。能完成真实主链才进入该范围正式实验；失败先采用19预登记的资源降级，不无止境加硬件。CPU工程对照仍可推进，软件验收与训练效果分开。

DEV探索可检查300—500条及合理训练设置，最多两轮资源/训练预实验；检查D旧正确池是否存在之前先冻结正式配方。正式D无足够池/确认组、C功效不足或未来无翻转，均保留负结果。不能查看正式结果后换checkpoint、加训练轮、改特征或放宽阈值再称主实验；若确需新方案，另登记为探索，或用未使用的新数据/未来run启动新评价。

三月完成五基线/两消融和所有预算。不稳定优势、主指标NA或无足够证据时，停止“优于基线/广泛有效”主张；完整系统、正确协议和诚实负结果仍可构成应用开发论文内容，最终以学院/导师要求为准。可选算法调整按17额外约束，默认不启动，不以反复调参拖延交付。

结果表在真实运行前留空。数据、权重、合法性、独立性、统计功效、最强对照兼容性和单人盲态均是需披露的限制；文档审查降低已识别风险，不代表已经排除所有未知问题。

