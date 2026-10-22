# 指标、候选发现、确认与套件算法

文档版本1.3，2026-10-22。算法版本`regression-v1`；所有浮点内部双精度，API返回0—1比例；UI乘100，差值显示“百分点”。前端不重新做统计。此次补齐真实权重更新与推理稳定性边界，不改变选择公式、阈值或同分规则。

## 1. 成对指标（ALG-01）

对同一合法范围内每行定义old_ok、new_ok。a=双方正确，b=旧对新错，c=旧错新对，d=双方错误。n=a+b+c+d。两份预测必须覆盖完整scope且100%合法、一一匹配；缺失、重复、额外ID、超时或非法标签使整个成对分析前置校验失败，不通过删行制造更好指标。执行覆盖率/失败类型另行报告，不把执行失败当作普通分类错误。

模型应用指纹不等于权重指纹：`ModelVersion.content_sha256`包含权重与推理配置等应用身份；真实训练更新另要求`weights_sha256`不同、`inference_config_sha256`相同，并保留父版本与训练产物来源。权重来源不明的外部预测只能说明用户声明的版本行为，不能由文件格式合法推出确有权重修改。具体见03及19。

- old_accuracy=(a+b)/n；new_accuracy=(a+c)/n。
- accuracy_drop=old_accuracy-new_accuracy=(b-c)/n，正值表示下降。
- negative_flip_rate=b/n；positive_flip_rate=c/n。
- old_correct_regression_rate=b/(a+b)，若a+b=0返回null，不用0掩盖无分母。
- macro-F1在冻结完整label_vocab上计算，缺少的类按zero_division=0；报告并列各类support，避免把无样本类误读为实际失败。
- n=0：INVALID_SCOPE，不能输出0%准确率。

混淆变化单独由D聚合：对每个非零旧/新混淆单元(gold_label,prediction_label)，输出old_count,new_count,delta=new_count-old_count。按abs(delta)降序，再按gold/pred标签字节升序。Analysis/Report内只嵌前50项及total_nonzero/truncated，完整结果走分页confusions接口；不把全矩阵塞进每个Slice的PairedMetrics。

夹具12行：a=6,b=3,c=1,d=2；旧准确率0.75，新准确率7/12，drop=1/6，NFR0.25，positive1/12，旧正确样本退化率1/3。见contracts/fixtures。

## 2. 候选发现（ALG-02）

输入仅D的文本特征与成对正误。默认配置：max_depth=2、min_discovery_support=30、min_discovery_drop=0.05、top_m=20、duplicate_jaccard=0.90、feature_catalog_version='surface-v1'。

1. 从03固定离散特征生成原子`feature==value`，feature按名称、value按canonical JSON字节排序。
2. 枚举单原子及不同feature的两原子合取；条件排序形成唯一canonical predicate。禁止同特征互斥值和空条件。
3. 在D统计n、a/b/c/d；只保留n≥30、b>c且drop≥0.05的候选。
4. rank_score=(b-c)/sqrt(n)。按score降序、n降序、predicate canonical字节升序稳定排序。
5. 按排序贪心去重：若与已保留候选D成员Jaccard≥0.90则略过；保留最多20项。去重不能使用C成员。
6. candidate_set_hash = SHA256(算法版本+配置hash+有序谓词列表+各D成员ID摘要)。写入后只读。

不声称枚举算法新颖。SliceLine/弱分组树是强对照，见11。P0先实现可理解、可验证的枚举器，不能依靠LLM命名的自由文本条件。

## 3. 固定家族的独立确认（ALG-03）

默认alpha=0.05，min_confirm_support=40个独立component，min_confirm_drop=0.05。这些是固定设计参数，不是已证明最优值，也不构成足够功效保证。家族是**冻结后的全部m个候选**，不能看C后挑出显著项缩小m。

`evidence_mode=CONFIRMATORY`才运行本节确认。LLM模型对须先通过DEV稳定性门：每版本固定100条DEV样本各推理3次，全部合法且解析标签逐例完全一致；按SHA256('stability-v1|42|'+sample_id)升序取前100，hash同分按sample_id；不足100条不能进入LLM确认模式。同时冻结推理后端、精度、提示词、标签映射、解码及重试策略。零观察变化只是小样本稳定性证据，不证明未来绝对确定。任一变化须先固定确定性/CPU推理再重做DEV门；仍有变化或无法提供记录则`DESCRIPTIVE_ONLY`，可做成对计数和发现展示，但不执行C显著性确认、不输出CONFIRMED_REGRESSION。Slice保持PROPOSED、confirmation=null，confirm请求409且不读取C。不得把三次重复行当成三倍独立样本。API/其他随机输出同样不能绕过本门。适用范围、冻结产物与登记字段见11/19。

确认时对每个slice在C按03选独立代表，得到n,a,b,c,d。若n<40，状态INSUFFICIENT_SUPPORT，p_raw=1；无论n多少，b+c=0时p_raw=1。否则使用成对单侧精确McNemar：`scipy.stats.binomtest(k=b,n=b+c,p=0.5,alternative='greater').pvalue`。[S07]

零假设是旧对新错与旧错新对概率相等，备择是净退化。这个p值**不是“下降超过5个百分点”的检验**；5个百分点是另加的实际效应门槛。

Holm：所有m个p排序p(1)≤…≤p(m)，`p_adj(i)=min(1,max_{j≤i}((m-j+1)*p(j)))`，再映射回slice。与statsmodels(method='holm')对照。[S08] 其家族错误率解释依赖单个p值在零假设下有效；同组件多行不独立、推理噪声或反复窥视C不能靠Holm自动修复。保证范围仅本次冻结家族，不是多次模型升级、多个语言/数据集的终身总体保证。实验方法比较按11先冻结各配置候选并集再统一确认。

若n≥40且p_adj≤0.05且drop≥0.05 → CONFIRMED_REGRESSION；n<40 → INSUFFICIENT_SUPPORT；其他 → NOT_CONFIRMED。即使p显著但幅度不足门槛，也显示原始值并标NOT_CONFIRMED，不隐去。

显示的95%成对bootstrap区间：对component代表的z=old_ok-new_ok整体重采样2,000次，seed由SHA256(analysis_id|slice_predicate_hash|42)前8字节获得，区间取分位数2.5%和97.5%。**区间为描述性近似、未做同时覆盖修正，不参与确认状态，不可称家族级置信保证。**

摘要：任一确认退化→REVIEW_REQUIRED；无候选或任一支持不足→INCONCLUSIVE；其余→NO_CONFIRMED_REGRESSION。DESCRIPTIVE_ONLY一律显示INCONCLUSIVE及推理/来源限制，confirmation及确认检验字段为null（成对描述计数仍保留），不伪装完成独立确认。始终显示“未确认退化不代表已证明安全/非劣”。本系统不实现S06的非劣认证，不自动部署模型。公开基准的组件抽样独立性仍是建模假设，不能把显著性解释为对所有真实业务或训练因果效果的保证。

## 4. 解释、重叠与人工审查（ALG-04）

同一实例可属多个slice，计数不能相加当不同错误总数。UI显示全局distinct b和各组重叠提示。D中的混淆对、代表文本仅解释关联，不做因果归因。

人工review_flag取UNREVIEWED/NEEDS_ATTENTION/DISMISSED_WITH_NOTE，DISMISSED需10—1000字备注；统计状态保持不变。Review不改变机器report verdict。API辅助说明仅为选做，不参与标签、统计或默认验收；如以后实现，只能引用已有slice_id/case_id及数字，不新增统计证据。

## 5. 有限预算套件精选（ALG-05）

输入：已完成Analysis、D样本和旧模型正确性、预算B∈[1,500]。候选池P={D中old_ok=true}；若空，422 NO_ELIGIBLE_CASES。

义务集合U：每个CONFIRMED_REGRESSION分组一个义务（权重2）；P中每个gold_label一个义务（权重1）。即使没有确认分组，也保留类别义务，不伪造退化分组。样本覆盖其所属的确认分组与其gold类别。使用C的**确认结论**选择已冻结分组可以；不取C具体样本或用C重新定义谓词。

每轮在未选样本中最大化：

`score = 1000 * 新覆盖义务权重 + 10 * historical_negative_flip + diversity`

historical_negative_flip是该样本在本次D旧对新错为1。diversity∈[0,1]是归一化字符TF-IDF向量到已选集合的最小余弦距离；首次均为1。向量器**只在D候选池拟合**，不复用含C/A的特征。每轮更新，直到min(B,|P|)。gain为整数、H为0/1、D为0—1，所以在实数运算下该公式等价于按(gain,H,D)词典序降序、最终ID升序。**实际实现直接比较元组，不把浮点D加到1000级标量后排序**，以免微小距离差被舍入造成假同分；展示公式仍保留。1000/10只是优先级编码，不代表真实价值比例或已验证最优权重。组/标签权重2:1、覆盖优先、每组一次覆盖及字面多样性均是待验证设计假设。它是工程启发式，不提供未来退化检出最优保证。五基线、两消融和如何调整见[17](17-baselines-and-algorithm-evolution.md)。

**特征与截断精确定义**：义务在完整P上建立，不在截断后重定义。N=|P|，L为标签数，K=min(5000,N)。N>L时每标签配额q_l=1+floor((K-L)*(n_l-1)/(N-L))；剩余名额按上述比例的小数余数降序分配，余数相同按标签UTF-8字节序。N=L时每标签1个。每标签按SHA256('pool-v1|42|'+sample_id)升序取q_l，hash同值按sample_id。这样保留全部标签；某退化组可能失去代表，义务仍保留并报告未覆盖。

在截断后的P'上拟合用于多样性的独立TfidfVectorizer：analyzer='char',ngram_range=(2,4),min_df=1,max_features=20000,lowercase=false,sublinear_tf=true,norm='l2',dtype=float64。输入使用03 normalize_text，按sample_id排序fit；记录词表/IDF摘要。恰有一方是零向量时距离约定1；两方均为零向量时距离0。不得复用模型训练向量器或读取C/A。

复杂度：距离采用稀疏矩阵分块更新，不建立N×N全量矩阵。导出config包含seed、pool_cap、pool_strategy_version='stratified_hash_v1'、vectorizer全部上述参数、selection_formula_version='weighted_lexicographic_v1'、feature_catalog_version。相同输入与锁定依赖必须产生同一ID序列。

输出每例sample_id、text、gold、基准旧预测、覆盖义务、selection_rank、选择理由、来源hash。报告未覆盖义务及实际size；预算不够时不能声称覆盖完整。套件内容hash不含创建时间，但包含有序样本内容、义务、算法/配置和源analysis指纹。

具体suite hash payload按键排序canonical JSON为`{dataset_content_sha256,labelset_sha256,source_candidate_set_hash,algorithm,config,budget,obligations,items}`；排除suite_id/project_id/source_analysis_id/创建时间/hash自身。obligations按id字节排序，items按rank排序。预测与gold不允许发布后改写。

这是**已有标签的套件压缩与后续重放**，不是省下首次发现D+C的评测费用。报告成本分开列“建库成本”和“每次未来版本重放成本”。

## 6. 套件重放（ALG-06）

仅同labelset_hash可重放。每条预测与套件gold比较，全部合法且全对→PASS；任一合法错误→FAIL；执行失败/不完整/非法标签→ERROR。默认容忍错误数0，可选设置不在P0开放。原旧模型预测无需重新运行，保留快照供对照。

PASS只表示这个有限套件通过。它不能覆盖全体业务、替代C的独立确认或证明未来模型安全。重放结果不能反过来修改同一套件；要更新用例创建新SuiteVersion。

## 7. 模块接口（Python）

```python
def compute_metrics(rows: list[PairedPrediction], label_vocab: list[str]) -> PairedMetrics: ...
def discover_slices(rows: list[DiscoveryRow], config: DiscoveryConfig) -> CandidateSet: ...
def confirm_slices(candidates: CandidateSet, rows: list[ConfirmationRow], config: ConfirmConfig) -> list[SliceResult]: ...
def select_suite(pool: list[DiscoveryRow], confirmed: list[SliceResult], config: SelectionConfig) -> SuiteSelection: ...
def judge_replay(items: list[SuiteItem], predictions: list[Prediction]) -> ReplayResult: ...
```

类型字段以contracts定义为准。统计函数纯函数，无DB、网络、LLM访问；传错role抛RoleViolation。生产配置门槛不可降低以通过测试；单元夹具通过测试专用显式config覆盖，不混入默认环境。

## 8. 算法版本与开发调整

默认只评价预先登记的固定初版，不以改出更高分作为毕业验收条件，不开放网页调参接口。M07实现固定初版，M11在lab实现五基线、两消融及正式评价。模型权重训练与selector调整是两件事：TRAIN训练真实模型版本；DEV试训/稳定性预实验；D/C/A评价诊断与套件。模型训练脚本属于离线实验准备，不扩成网页训练平台。

如另行启动算法调整分支，只依据DEV或独立开发语料及开发未来模型；正式D/C/A与正式未来目标预测不用于选权重。这里的“选权重”指选择策略参数；模型训练权重亦不得读取D/C/A。初版和改动均保留，不覆盖旧Suite或Report。固定版本链、最少证据、噪声门及成本见11/19。

17给出可选调整分支的两轮上限、开发晋级门槛、权重/顺序/组内代表数的受限调整和停止规则；至少3条开发链的门槛只约束该分支，不是固定初版或P0软件的毕业门槛。改变排序、覆盖定义、向量器或同分规则，均视为新算法/配置版本；先修合同与fixture，再改生产实现。仅在lab评价的变体不能使用生产算法名导出成普通Suite。
