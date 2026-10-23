# v2 验证计划与研究关卡

状态：**PLANNED_NOT_IMPLEMENTED**。下列测试文件、fixture、CLI和研究结果尚未实现或执行；现有Demo测试仍只证明旧描述性流程。本文将[三个研究问题](../../research/v2/source/01-research-position.md)、[算法原案](../../research/v2/source/03-algorithm-spec.md)与[实验关卡](../../research/v2/source/04-experiment-protocol.md)转成可核验的未来验收条件，不承诺HGC胜出。

## 1. 证据分层

| 层次 | 要验证什么 | 不能据此声称什么 |
|---|---|---|
| 单元/精确合成算例 | 历史截止、风险分母、选择序列、预算和算术正确 | 真实模型更新有效、未来Recall有保证 |
| 本地集成/故障注入 | 工件hash、访问层、冻结、解封/恢复、成本与来源保真 | 操作者从未私下接触目标、恶意插件被完整沙箱隔离 |
| 浏览器验收 | 只读证据导入、来源/访问/NA/费用展示一致、转义 | UI运行即研究假设成立 |
| G0—G3真实实验 | 真实版本、开发信号、机制与独立目标评价 | 训练检查点、selector种子或文本行成为独立更新重复 |

每项执行记录包含测试ID、命令、代码commit、锁文件hash、输入manifest、机器环境、退出状态与输出hash；未跑为`NOT_RUN`，缺方法为明确缺项，不能写PASS。既有Demo与v2使用不同fixture、schema和验收报告。

## 2. 精确fixture（均为未来新增）

### FX-TIME：四版本、修复与新错误

以下六例均以gold=A说明时间逻辑，完整导入fixture另配TRAIN的A/B词表和唯一文本/组件。这里只是工程正误序列，不是真实模型预测。

| ID | f0 | f1 | f2 | f3 | 预期分类 |
|---|---|---|---|---|---|
| repair-recur | A | B | A | B | H0=1，f2修复后f3再错；在P和R* |
| novel | A | A | A | B | H0=H1=0；在P和R*，历史未见 |
| repair-stable | A | B | A | A | 有历史翻转但目标未复发；在P，不在R* |
| stable | A | A | A | A | 在P，不在R* |
| latest-flip | A | A | B | A | H1=1但不在P，不能计入suite或R* |
| persistent-wrong | B | B | B | B | 不在P；低准确率不等于负向翻转 |

精确预期：P=前四例、|R*|=2；P内H1恒零。`S=[repair-recur,stable]`时实际预算=2、检出1、Recall=1/2、Precision=1/2、Enrichment=1；`S=[novel]`时检出1、Recall=1/2、Precision=1、Enrichment=2。历史未见分母与修复后复发分母各1，须分别输出。不得把latest-flip放入未来分母。

### FX-RISK：净零但高翻转风险

100个独立D组件，gold均A。群体g有20例：4例为A→B→A、4例为B→A→B、12例为A→A→A；其余80例为72例A→A→A和8例B→B→B。两个历史转移中，g分别都是a=12,b=4,c=4,d=0，净下降=0；全局e=88、b=4、p0=1/22。

在m=30时，g的e=16，收缩率`p=(4+30/22)/(16+30)=59/506`，超额风险`u=18/253`；两转移均有效，q=1、w=18/253。风险候选应保留它，旧净下降发现器可不保留；不能给它套“McNemar已确认净退化”。同一例不会在相邻两个转移都负翻，群体重复与单例重复须分清。

### 其他必备算例

| Fixture | 精确边界 |
|---|---|
| FX-ZERO-R | P非空但目标全部正确：R*=0，Recall/Enrichment=`null`并有`NO_TARGET_FLIPS`；Precision=0（S非空），不删除该链 |
| FX-ZERO-W | 所有w=0或没有可用历史：HGC显式fallback到Facility；无除零，结果与同U/K的Facility序列一致，记录原因 |
| FX-SUPPORT | 全局e=0的转移整体排除；某组e<10则u=0且仍在有效转移的q分母；机会数不是D行数 |
| FX-OVERLAP | 两群体重叠，独特检出按sample_id/组件约定计数；不把群体命中相加成未来错误总数 |
| FX-PREFIX | 固定输入/参数/seed至最大B计算一次，B1<B2的suite严格为同序列前缀；hash不受输入行序影响 |
| FX-BUDGET-ALIAS | |P|=7，20/50/100/200均映射b=7；四名义预算保留别名，只计一个有效预算点；重复注册相同名义预算拒绝 |
| FX-COST | B_total=100、探测30次＋选择后推理80次，即使重叠10个ID仍有110次执行，超预算；全池500次f3概率不属于B=100主表 |
| FX-TIE | risk-top、HGC贪心边际同分、Legacy元组同分按source_i UTF-8次序；随机方法按注册seed与确定算法复现 |
| FX-SOURCE | 合成权重/预测只能标SYNTHETIC；外部声明不升级为独立核验来源，缺少实际训练产物不能冒称真实更新 |

Risk-LR另用时间前缀fixture：预测H_t时可用f_t参考分数和H_<t/E_<t；把当次H_t放入“此前翻转数”必须拒绝。t=0明确cold-start/missing-history标记，不能用0假装测得历史无风险。正式f2→f3输入可含H0/H1，不能含H2或任何f3派生特征。DEV_SELECTOR训练样本不得来自正式TEST；DEV_MODEL曾参与模型选择的分数偏差单列限制。

## 3. 测试与研究问题追踪

下表中G0—G3是研究出口，`U/I/E`分别为未来单元、集成、浏览器验收ID。测试通过只解锁相应研究步骤，不替代真实G关卡材料。

| ID | 未来验证内容与可观察断言 | 对应RQ / 门 |
|---|---|---|
| V2-U01 | NFKC/同group传递组件、冲突排除整组件、TRAIN类别覆盖，实际计数与source hash可重算 | RQ1 / G0 |
| V2-U02 | v2 TEST80/10/10与DEV两个用途可重现且组件互斥；旧Demo50/25/25结果不变 | RQ1 / G0 |
| V2-U03 | FX-TIME的P、H0/H1、R*、历史未见/修复复发分母与指标精确相等 | RQ1/2 / G1 |
| V2-U04 | FX-RISK/FX-SUPPORT的e、p0、u、q、w精确匹配；净零风险不被净下降门槛误删 | RQ2 / G2 |
| V2-U05 | 最多30组、Jaccard≥.9去重、权重/P支持/谓词同分规则稳定，P外组不建目标 | RQ2 / G2 |
| V2-U06 | 非负TF-IDF、≤256分层hash锚点、零向量K=0、固定U/K；C/A不参与fit | RQ2/3 / G2 |
| V2-U07 | HGC精确边际、k=3饱和、λ端点、FX-ZERO-W与小集合穷举代理目标核对 | RQ2 / G2 |
| V2-U08 | FX-PREFIX/FX-TIE；重复运行、输入重排行和分块相似度不改变有序选择 | RQ1/3 / G2 |
| V2-U09 | 全4.1方法的最小可手算例；Random无放回、Stratified最大余数且小预算允许零配额、PastFlip按次数/有效机会 | RQ1 / G2 |
| V2-U10 | Risk-LR时间截止/cold-start/未知类别映射；禁止H_t进入自身输入，固定C=1/L2/balanced | RQ1/2 / G2 |
| V2-U11 | Behavior-Anchor代表规则/随机性与method_origin一致；Legacy-adapt精确(gain,H,diversity)且H为任意历史 | RQ1/2 / G2 |
| V2-U12 | f2概率四种不确定性方向正确；全标签序列分数合同明确；首token分数不能冒充类别分布 | RQ1 / G0/G2 |
| V2-U13 | Grad-PD玩具CPU梯度与有限差分方向核对；f2/f3参数坐标/类表/特征hash对齐，否则拒绝 | RQ1/3 / G2 |
| V2-U14 | FX-ZERO-R、零子组分母、FX-BUDGET-ALIAS，NA带原因；不把别名算独立结果 | RQ1/3 / G1/G3 |
| V2-U15 | 同一链20个selector seed先聚合；4检查点不变4链；统计家族/比较器/hash固定 | RQ1/3 / G3 |
| V2-U16 | FX-COST、缓存/失败attempt归属、共享成本分摊守恒、两账公式与实际执行次数 | RQ3 / G0/G3 |
| V2-I01 | 注册字段/跨实体引用校验；正式未决字段、缺必需方法或缺审批不得开始正式选择 | 全RQ / G0/G2 |
| V2-I02 | no-f3-path：历史选择上下文/递归manifest含目标路径即拒绝；文件解析器对sealed根拒读；目标探测结果不回流HGC | RQ1/2 / G2/G3 |
| V2-I03 | 改动输入实际字节却伪造64位hash，读入、冻结、评价、view导入均拒绝；符号链接逃逸不通过 | 全RQ / G0/G3 |
| V2-I04 | 必需cell失败/少seed/非法budget alias/更换配置/缺方法阻止FreezeMatrix；目标前批准UNAVAILABLE才可限定适用范围 | RQ1 / G2/G3 |
| V2-I05 | 主矩阵冻结前完整f3解封失败；声明白盒/有限探测只按能力授权。全池增强须父主矩阵及自身registration先冻结，再取得输入、冻结增强suite后计分；冻结后改suite字节失败 | RQ1/2 / G3 |
| V2-I06 | select中断续跑复用同hash单元；已冻结不能覆盖；evaluate中断同session续算但不重新“未见” | 全RQ / G3 |
| V2-I07 | 真实CPU训练保存恢复、模型/训练数据来源一致、抽样/优化实现可复验；非随机lbfgs仅换seed不冒充独立链 | RQ3 / G0 |
| V2-I08 | 目标缺行、重复、未知标签、非法输出、混run均拒绝计分；失败不可missing-as-wrong或筛成功行 | RQ1 / G0/G3 |
| V2-I09 | 至少一个SliceLine/DivExplorer安装锁定并通过适配算例；非负目标与旧正确分母；原样/重实现/适配明确 | RQ1/2 / G2 |
| V2-I10 | 白盒/参考分数/目标探测分表与成本严格保留；增强方法超B不能混入主表，不能下调其已花费用 | RQ1/3 / G3 |
| V2-I11 | 数据/方法来源、许可、代码版本、完整matrix/成本随bundle；无C/A逐例、私有路径/原始目标响应 | 全RQ / G3 |
| V2-E01 | 导入已校验bundle、刷新/重启后hash与选择序列不变，旧Demo记录仍可查看且显式legacy | 全RQ / G3 |
| V2-E02 | 页面显示P/R*分母、零R为NA、实际/名义预算、seed链内聚合、各访问层与两账；JSON/HTML与页面一致 | RQ1/3 / G3 |
| V2-E03 | 未评价不显示f3指标；评价后仅授权P/D证据，角色越权拒绝；页面没有训练/解封/调参按钮 | RQ1/2 / G3 |
| V2-E04 | 标题、sample文本、来源、失败说明含HTML均转义；静态报告无脚本；移动/键盘/长文及错误态可用 | 全RQ / G3 |

V2-I05同时验证D15分支：CORE_PRE_TARGET登记中出现TARGET_FULL_POOL立即拒绝；增强登记缺父主矩阵hash拒绝；父引用存在但实际工件未冻结仍拒绝；增强方法取得必要输入后可选样，但不能篡改父历史/风险/套件。增强参数若在目标曝光后调整，标探索，不纳入预登记比较。所有分支不因时间戳字符串合法就视为真实完成。

FX-PREFIX只断言HGC/Facility或明确固定排序方法，不把Stratified最大余数的各预算配额误测为前缀。探测适配另验全部探测ID在最终套件、唯一且属于P，实际调用不超过预算；FX-COST超限样本仍必须失败。Schema允许λ=0/1仅作ABLATION，PRIMARY/DEVELOPMENT保持六配置范围。

## 4. 全方法资格与机制核对

核心4.1方法逐项出现在 MethodRegistry/expected matrix；不能以“已实现十个”代替点名缺失Risk-LR或Behavior-Anchor。标签层含random、stratified、past-flip、kcenter、facility、risk-top、risk-lr、behavior-anchor、legacy-adapt、hgc；参考分数层另含ref-maxprob/ref-margin/ref-entropy/ref-deepgini。分数版Risk-LR或Behavior-Anchor是另一个登记配置，不能悄悄提高标签层信息量。

CPU Grad-PD为核心白盒参考：只在参数坐标可比链计算`∇θℓ(f2,x,y)·(θ3−θ2)`等已登记方向量，精确排序组合按适配说明固定。若各版TF-IDF词表/IDF或类别坐标不同，先生成有明确同坐标合同的对照链，不直接相减错位参数；不能将不兼容默认为完成比较。官方GBV-PD的PCA/旧损失排序核查与差异单列，不宣称一阶参考即完整原文复现。

候选核心配置只允许λ∈{.25,.5,.75}×m∈{10,30}，共≤6个；默认k=3，k=1属于机制消融。去群体/λ=0、去代表性/λ=1、等权w、单历史/多历史、Risk-Top与组内随机代表分别登记，不与6配置做全乘积。最多2轮开发；保留每轮所有配置和失败，正式目标绝不用于选主配置或主比较器。

## 5. G0—G3：可执行的出口与停止规则

来源中“稳定接近”“足够信号”等未给齐数值。未来实现必须校验机器可读的`gate_policy`：每家族最低有效链数、最低|R*|、允许缺项、开发接近容限/成本上限、主比较器选择规则及最终统计接受方式均有值或显式不适用原因。fixture可用DRAFT policy；正式study不能将未决字符串当默认通过。

| 门 | 必须形成的材料与判定 | 不通过时 |
|---|---|---|
| G0 数据与资源 | 两数据集的来源/许可/hash及清理清单；DEV隔离；至少一条四版真实CPU链完整合法、固定环境稳定并可恢复。开发矩阵计划每家族3条，后续按实测扩展。GPU分支须DEV单次短训测wall/峰值显存/吞吐/标签合法性及稳定性，按同口径估计总量，与初始20 GPU小时护栏比较 | CPU数据/版本失败先修；GPU预算超限/不可用可关闭神经扩展并限制结论，不能把整个G0写成GPU通过 |
| G1 可评价信号 | DEV_SELECTOR开发目标中按家族/链给出P、R*、新错/复发分母与零翻转比例；至少两个开发家族满足注册的有效链/翻转阈值，链间目标事件确有变化，所有零信号链保留 | 只按预登记开发规则增加样本/更新强度；仍无信号则报告当前任务不支持方法检出评价，不挑正式坏版本 |
| G2 方法机制 | 核心方法/访问资格/CPU方向参考/一项可安装发现器核查齐全；≤6配置、≤2轮在两个开发家族按注册接近规则与成本上限评估，消融完整；冻结主方法、比较器、特征、表示、统计与全部方法预算seed | 停止加配置，转比较研究或简化方法；不得靠增加UI页面替代方法证据；正式评价可登记为比较/描述目的 |
| G3 最终评价 | 实际全矩阵冻结、目标首次解封/恢复日志、共同P分母、所有预算/链/成本和NA、预登记配对统计/多重比较、方法来源/失败项齐全；按已批准结论规则决定支持哪类表述 | 正式失败/负结果照报，不从矩阵删输家或再调参；推断证据不足即限定为描述性结果 |

为使开发工具可先实现，可在DRAFT中提出“每开发家族3条、至少2条有效链且每条R*>0，至少两个家族可评价；G2两家族的链内seed均值再按链汇总，与冻结强基线差≥−.03且增量选择账不高于已登记成本上限”的初始检查建议。**这是待导师/开发预实验批准的工程补充，不是源文已冻结门槛、统计非劣检验或既得结果。**链数、容限、成本比和“变化”的判定须在正式登记前以决策ID固定；不适用统计推断时明确仅作描述。

最终“更好”原案建议B=100的Recall增益≥.05并有足够跨更新证据；“至少持平”原案建议配对差的有效单侧95%下界>−.03，且总成本下降≥20%或有明确较弱访问要求。数值及统计可识别性须导师在正式解封前认可；样本少时不以“不显著”替代等效/非劣。主比较器和Holm家族不能看正式结果再选。C上的组件bootstrap或McNemar也不能提供跨模型普遍有效性的证据。

## 6. 计划测试命令与记录

以下是[实施计划](07-implementation-plan.md)对应未来包结构的目标命令，**当前没有这些测试文件，禁止当作已运行记录**：

```text
# PLANNED_NOT_IMPLEMENTED；在未来lab目录执行
uv run pytest tests/unit/test_temporal_pool.py tests/unit/test_risk_weights.py -q
uv run pytest tests/unit/test_selectors.py tests/unit/test_costs.py -q
uv run pytest tests/integration/test_access_boundary.py tests/integration/test_freeze_resume.py -q
uv run pytest tests/integration/test_method_adapters.py tests/integration/test_evaluator.py -q
# PLANNED_NOT_IMPLEMENTED；在未来experiments目录执行
uv run pytest tests/test_cpu_chain.py tests/test_gradient_direction.py tests/test_inference_contract.py -q
# PLANNED_NOT_IMPLEMENTED；未来扩展现有浏览器测试
cd e2e && npm test -- research-v2.spec.js
```

每阶段先写有独立预期的失败算例，再实现；不写只复述实现的镜像测试。正式run包中的`validation-manifest.json`汇集V2测试记录和G门决策，不能复制旧Demo的67测试/浏览器结果冒充新研究能力。

## 7. 可选确认与模拟扩展

核心先做重复风险、目标新风险、历史修复/反转、重叠群体四类可控模拟，明确合成性质。只有主张群体统计控制时才做1000次完整发现/确认模拟；每个候选局部b/c须交换对称，并报告FWER的Monte Carlo区间。潜在真群体的一对一Jaccard匹配阈值预登记，不让多个返回组重复命中同一真组抬高召回。

若启动C净下降确认，所有方法冻结候选并集后统一Holm；支持40、b=2/c=0时单侧p=.25的反例须通过，不能称支持40足以检出5个百分点。每发现器同K=10的比较与核心HGC最多30风险组是两个不同设置，不能混用。C结论不反向切换HGC权重；更多发现器、语义族和A诊断仍为扩展，不进入主选样P/R*的评价分母。
