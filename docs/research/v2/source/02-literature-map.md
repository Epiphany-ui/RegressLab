# 文献、代码与复现路线

检索截止2026-10-23。定向检索，不是穷尽性系统综述或创新认证。检索式围绕 paired model regression、negative flips、test selection/prioritization、slice discovery、future model evaluation，并沿最近工作的参考文献查找。优先作者全文、会议论文集、arXiv与官方项目。**代码可访问不等于已经成功复现；本轮没有执行这些论文的实现。**

## 1. 先明确三类不同任务

1. **标注预算：**可以跑完新旧模型，但只为少量样本取得正确答案。DeepGini、RiskBlend、MetaSel等主要在这一侧。不能由“只检查B条”宣称少跑了新模型。
2. **执行预算：**正确标签已存在，新模型只能执行部分测试。GBV-PD利用参数差做到执行前排序；HGC拟在不读取目标参数条件下研究这一任务。
3. **小集估计准确率：**选一小批题估计整个模型的平均分。CES、PACE、DeepReduce、AnchorPoints和tinyBenchmarks的重要目标在此，不等于找到最多负向翻转。

本项目有公开gold，若全池新旧预测也已知，当前错误位置已经能精确计算；此时“找这些错误”不再是有未知量的预测研究。因此主实验必须保留未来目标结果，并在套件冻结后计分。

## 2. 回归样本选择：十项优先工作

### S1. GBV-PD，ASE2026：最直接的执行预算对照

*Evolution-Aware Regression Test Prioritization of ML-Enabled Systems using Gradient-Based Behavior Vectors*。[论文v2](https://arxiv.org/html/2606.28037v2)、[正式DOI](https://doi.org/10.1145/3832783.3834368)、[文中复制包DOI](https://doi.org/10.6084/m9.figshare.31830196.v5)。

在旧模型上计算每例损失梯度，以PCA压缩为行为向量；将新旧权重差投影到同一空间，估计损失变化方向，再与旧损失排序结合。无需目标模型测试推理，但需要标签、梯度、对齐权重和局部近似。评估Precision/Recall/nDCG/Enrichment及缓存与时间。读取全文方法、算法和成本章节；复制包页面未完整取得，不宣称跑通。原实验不是MASSIVE文本；最后层梯度是论文支持的配置，LoRA参数适配则需明示。v1有占位出版信息，以v2及正式DOI为准。

**影响：**“考虑更新方向且少跑新模型”已有直接方法，必须比较，至少实现可核对的一阶梯度方向性参考。

### S2. MetaSel，IEEE TSE2025：跨版行为学习已存在

*MetaSel: A Test Selection Approach for Fine-tuned DNN Models*。[全文v4](https://arxiv.org/html/2503.17534v4)、[DOI](https://doi.org/10.1109/TSE.2025.3612253)、[作者复制包](https://figshare.com/s/b4b1338873351ca01734)。

用两版logits、差值、类别一致性和OOD分数训练错误预测器，需要目标模型对候选集执行及带标签的训练/验证信息；目标主要是新模型错误，不只负向翻转。TRC分母与普通Recall不同，不可混名。方法和评价章节已查，包链接来自论文但未下载运行。文本OOD替换/轻量逻辑回归属于适配。

**影响：**不能把“新旧概率融合＋小预测器”直接当新点；放入增强访问对照。

### S3. RiskBlend，2026预印本：历史和变化风险融合的近邻

*RiskBlend: A Multi-Signal Framework for Test Input Prioritization in Machine Learning Regression Testing*。[全文](https://arxiv.org/html/2608.27704v1)。

融合历史验证错误邻近度、预测变化、边界变化和邻域变化，按验证APFD配置权重。文中的history含当前旧新版在验证集上确认的错误，不等同于只用过去更新；全候选上的两版概率已计算。预算主要是核验标签，原式针对二分类表格。检查了方法/实验；正文APFD-squared权重转换未写出完整公式，部分汇总权重与表格均值有差异，复现须固定解释。复制包见文中[Figshare](https://doi.org/10.6084/m9.figshare.32964359)，访问未验证完整代码，未找到另一个可核验官方GitHub。未核实正式录用。

**影响：**历史、变化和多样性组合并非空白；多分类与执行预算适配不能冒充原结果。

### S4. No Universal Signal，2026预印本：不要假定万能翻转信号

*No Universal Signal Predicts Sample-Level LLM Regression under Version Updates*。[全文](https://arxiv.org/html/2608.13607v1)、[作者代码](https://github.com/jiashengsally/llm-regression-signals)。

比较置信度、margin、attention entropy及跨版KL、似然/表示变化；以增量预测价值进行比较。主要验证是同一版本对内交叉验证，不是本方案的严格时间留出；多数信号已执行目标模型。全文方法与实验段已查，未运行代码。

**影响：**应比较强不确定性基线并报告任务/更新依赖，不预设跨版本变化信号一定更好。

### S5. DeepReduce，ISSRE2020：重用小套件并非新问题

*Cost-Effective Testing of a Deep Learning Model through Input Reduction*。[最终全文](https://dongjinhao-ruc.github.io/pdfs/issre20_cost.pdf)、[DOI](https://doi.org/10.1109/ISSRE5003.2020.00035)、[官方实现](https://github.com/DeepReduce/DeepReduce)。

先保神经元覆盖，再以分布KL准则增加代表样本。最终论文RQ4把原小集用于7种修改并重训的模型，评价聚合准确率误差。已查算法/RQ4；旧投稿与最终版数字不同，采用最终论文。不与同名的稀疏张量通信DeepReduce混淆。

**影响：**不能宣称首次把固定测试集用于未来修改版；主差异须是负向翻转目标和信息协议。

### S6. Anchor Points，EACL2024：最相关的文本小集对照之一

*Anchor Points: Benchmarking Models with Much Fewer Examples*。[会议记录](https://aclanthology.org/2024.eacl-long.95/)、[全文](https://arxiv.org/html/2309.08638v2)、[官方实现](https://github.com/rvivek3/AnchorPoints)。

利用多个历史模型对每例正确类的置信度相关性，经变换/聚类选锚点，估计模型表现与行为；已有模型家族留出。主目标是模型排名/分数，非专门的下一次负向翻转检出。方法和验证已查，未运行。

**影响：**HGC必须与历史行为聚类比较，不能仅比随机。少量历史模型是否足够是本项目要验证的限制。

### S7. tinyBenchmarks，ICML2024：历史模型与时间留出已有先例

*tinyBenchmarks: evaluating LLMs with fewer examples*。[会议论文](https://proceedings.mlr.press/v235/maia-polo24a.html)、[全文](https://arxiv.org/html/2402.14992v2)、[评测代码](https://github.com/felipemaiapolo/tinyBenchmarks)、[实验代码](https://github.com/felipemaiapolo/efficbench)。

基于历史模型×题目正确矩阵学习IRT表征、选择锚点，并估计新模型总分；包含时间留出。其100题经验结论不是对MASSIVE任意100题的保证，也不是回归错误保留率保证。方法/实验/附录已查；只有几条模型链时完整IRT可能不稳定，先用行为锚点适配，不强行复现庞大历史模型矩阵。

**影响：**“未来模型泛化”本身不够新，指标和少历史约束须明确定义。

### S8. DeepGini，ISSTA2020，以及简单基线复现研究

*DeepGini: Prioritizing Massive Tests to Enhance the Robustness of Deep Neural Networks*。[最终全文](https://qingkaishi.github.io/public_pdfs/ISSTA20-DeepGini.pdf)、[官方代码](https://github.com/deepgini/deepgini)。对概率分布计算 `1−Σp_c²`，高分优先；原目标是一般错误发现/重训，通常已运行被测模型全池。原实现依赖较旧Keras/TensorFlow，但评分公式容易独立实现。

[ISSTA2022复现研究](https://arxiv.org/abs/2205.00664)提示最大概率/entropy等简单方法很强；该复现本轮只核实摘要，没有完整审读。DeepGini本轮查了全文。使用f2概率的版本应标为Ref-DeepGini，不能冒充原论文使用f3概率的条件。

**影响：**不能只拿随机作基线，也不能只拿DeepGini代表全部不确定性方法。

### S9. CES，ESEC/FSE2019：分布匹配不等于翻转检出

*Boosting Operational DNN Testing Efficiency through Conditioning*。[最终全文](https://cs.nju.edu.cn/changxu/1_publications/19/ESECFSE19.pdf)、[DOI](https://doi.org/10.1145/3338906.3338930)、[作者代码](https://github.com/Lizn-zn/DNNOpAcc)。

Cross-Entropy Sampling匹配末隐藏层离散输出分布，降低操作准确率估计方差；这里cross entropy不是逐例预测与gold的交叉熵。需要候选隐藏表示；全文方法已查。当前主要研究错误检出，故作为相关路线而非必须加入的十一个主算法。

### S10. CASPER，2026预印本：群体＋有限目标探测的直接邻近工作

*CASPER—Change-Aware Slice Prioritization for Efficient Regression Testing of LLM-based systems*。[全文](https://arxiv.org/html/2608.00378v1)。

用多目标搜索从行为日志识别群体，再执行少量更新后代表实例估计变化影响并排序；实验面向SWE-bench类LLM系统。与“群体＋有限预算”很近，且目标探测属于必要成本。检查方法/实验段，未验证完整官方代码包；版本含占位出版信息，按预印本处理。

**影响：**HGC的“零目标探测”是约束差异，不是足以证明新颖的理由；可设相同总预算的探测式简化强对照。

## 3. 找出下降/高风险群体：十项优先工作

| 编号、来源及代码 | 已有方法 | 关系、复现与统计限制 |
|---|---|---|
| G1 **Model ChangeLists**, FAccT2024：[全文](https://facctconference.org/static/papers24/facct24-162.pdf)，[框架](https://github.com/HazyResearch/meerkat) | 对嵌入及两版损失拟合混合模型，进行解释与发布 | **直接成对先例**，含文本QA；有signed-rank和Bonferroni。未清楚建立独立确认集。不能宣称首次成对或首次多重校正；早期Mocha不另算独立方法 |
| G2 **AutoSlicer**, NeurIPS2022 deployment workshop：[全文](https://arxiv.org/pdf/2212.09032) | 搜索特征合取，比较同组current/baseline指标；分布式计算 | **直接成对先例**；Poisson bootstrap和t统计，未找到多重校正；独立官方源码未核实 |
| G3 **Slice Finder**, ICDE2019：[作者全文](https://arxiv.org/pdf/1807.06068)，[作者实现](https://github.com/yeounoh/slicefinder) | 可解释合取、树/格搜索、大而简单的错误子群 | 原单模型；扩展稿有α-investing与mFDR讨论，不可说统计控制完全空白；更改自适应流程后原保证不能直接继承 |
| G4 **SliceLine**, SIGMOD2021：[全文](https://mboehm7.github.io/resources/sigmod2021b_sliceline.pdf)，[原SystemDS实现](https://github.com/apache/systemds/blob/main/scripts/builtin/slicefinder.dml)，[第三方Python实现](https://github.com/DataDome/sliceline) | 稀疏线性代数、相对错误/支持度评分与剪枝 | 适合CPU谓词强基线；原目标非负，不能直接传入有负数的NF−PF沿用剪枝证明。DataDome不是原作者实现 |
| G5 **DivExplorer**, SIGMOD2021：*Looking for Trouble: Analyzing Classifier Behavior via Pattern Divergence*，[全文](https://divexplorer.github.io/static/DivExplorer.pdf)，[官方包](https://github.com/divexplorer/divexplorer) | 频繁项集、群体结果相对全局的divergence及Shapley解释 | 适配翻转二值结果可行；统计量不等于家族误报控制。长token词汇会让搜索爆炸，先固定表面特征库 |
| G6 **Domino**, ICLR2022：[全文](https://arxiv.org/html/2203.14960)，[官方实现](https://github.com/HazyResearch/domino) | 结合嵌入、标签/预测的误差感知混合模型 | 原单模型；其成对适配已由G1完成。更换成本地文本嵌入必须明示，不把原模型直接当成最强成对方法 |
| G7 **Spotlight**, FAccT2022：[最终全文](https://jrwright.info/deon2022spotlight.pdf)，[官方实现](https://github.com/gregdeon/spotlight) | 在连续表征中优化高损失的软区域与最小质量约束 | 有NLP案例；不是高斯混合算法。未查到通用多重校正保证；索引误写AAAI时以最终论文为准 |
| G8 **Edisa / DEIM**, TACL2023：[论文](https://aclanthology.org/2023.tacl-1.87/)，[官方实现](https://github.com/WenyueH/DEIM) | NLP的嵌入、预测置信与误差距离混合；语言特征解释和基准 | 文本任务很接近；原单模型，翻转伪任务应注明适配。语言特征置换检验不自动变成全部发现组的同时保证 |
| G9 **SemSlicer**, ASE2024：[论文](https://www.cs.cmu.edu/~ckaestne/pdf/ase24.pdf)，[官方实现](https://github.com/malusamayo/SemSlicer) | 根据用户语义标准，用LLM生成/优化群体成员标注提示 | 主要解决给定概念的成员标注，不是穷尽发现；有API成本。本轮不引入为必做；不能叫成未核实的TextSlice方法 |
| G10 **MCSD**, AAAI2026：[论文集](https://ojs.aaai.org/index.php/AAAI/article/view/40016)，[查阅预印本](https://arxiv.org/html/2501.19032v1)，[官方实现](https://github.com/h-yu16/MCSD) | 风险与流形紧致性优化，不依赖穷尽语义标注 | 预印本始于2025，但正式发表为2026；代码需Gurobi许可且示例适配成本较高，非本项目最低必做 |

以上全文已打开并定位方法/统计/评价段，不表示所有附录逐字审读；MCSD主要技术核查依据预印本，正式记录核对录用/年份。

## 4. 补充边界与最新检索

- [ACL2021 Regression Bugs](https://aclanthology.org/2021.acl-long.515/)研究NLP更新负向翻转及语言现象测试，是现象和诊断基础，不是本项目新定义。
- [RETAIN，EMNLPdemo2024](https://aclanthology.org/2024.emnlp-demo.31/)已用LLM解释迁移输出差异、标记群体。因此“生成分析文字/加个面板”不能作为方法贡献。论文可读，官方完整实现未核实。
- [Incremental SliceLine，BTW2025](https://mboehm7.github.io/resources/btw2025b.pdf)，[作者复现包](https://github.com/damslab/reproducibility/tree/master/btw2025-incsliceline-p11)已研究模型/数据更新时重用挖掘状态。增量搜索加速也需比较前人。
- [PlaneSpot / SpotCheck](https://arxiv.org/abs/2207.04104)，[官方基准](https://github.com/njohnson99/spotcheck)可作为简单聚类与可控真群体实验参照；本轮全文读取受限制，只查作者页面、摘要与代码，不据此写细节保证。
- [PACE](https://tjusail.github.io/people/chenjunjie/files/TOSEM20.pdf)，[官方实现](https://github.com/pace2019/pace)：聚类、原型、少数空间探索，主要评估准确率估计。全文方法已查；普通k-means不等于精确复现PACE。
- [MCP，ASE2020](https://conferences.computer.org/ase/pdfs/ASE2020-4sGQAuWfliLhpf5VK4ZM4u/676800a410/676800a410.pdf)，[官方代码](https://github.com/actionabletest/MCP)：按top-two类别边界聚类并优先近边界样本，主要用于重训。可作参考分数访问层的增强基线。
- [DISCERN，2026预印本](https://arxiv.org/html/2609.17560v1)在分歧区域取得标签并做成对风险差审计，节省的是标签，前提含新旧模型流量预测；不是不执行新模型的省推理方案。附录称代码将随正式发表释放，不能写已公开可复现；其页面提交日期与arXiv编号月份有不一致，正式引用需再核对。
- [2026 LLM代码任务复现研究](https://arxiv.org/abs/2606.27601)再次区分准确率估计与早期错误发现；本轮核实摘要及方法片段，未完整复核所有实现。
- [FSE2026 测试目标与分布变化实证研究](https://asi.cs.cityu.edu.hk/news/fse-test-selection-metrics.html)，[DOI](https://doi.org/10.1145/3797086)提示不同测试目标下排名不同；本轮核对作者项目摘要，未审读最终全文，不引用其具体数值作论据。
- [TEASMA](https://arxiv.org/html/2308.01311v4)评估测试集检错能力，不是直接的选样算法。不要把测试充分性预测器误当所有预算下的回归选择器。

## 5. 实际复现顺序

先用统一候选池实现Random/Stratified/PastFlip/参考不确定性/Facility/KCenter；同时复现一项谓词发现方法及其小算例。其次实现Risk-Top、Risk-LR、HGC、历史行为锚点和CPU方向梯度参考。然后加入直接paired mixture诊断对照与可取得的GBV-PD配置。最后才考虑需要新目标探测/全池预测的CASPER、RiskBlend或MetaSel适配。

“先后顺序”不允许省掉最近强基线后就下优越结论；若未能复现，记录依赖、包版本、失败和算法实现依据，把结论限制为已完成比较。

每个实现须有 `method_origin`（原样/重实现/适配/启发）、原始论文版本、代码commit、访问层、目标函数、超参数、成本账和未实现差异。不得给改过目标的方法保留原名而不加后缀。

## 6. 尚未确认的创新点

本轮没有找到足以直接断言“少历史、标签访问、当前正确池、下一次文本更新负向翻转、群体饱和覆盖”这一**精确设置**已被完整解决或完全空白的证据。这个限定组合只是候选切口，仍需在最终算法冻结后沿S1/S6/S7/S10及群体工作继续做引用前后追踪。

可检验的改进在于历史风险迁移和互补选样是否有额外收益；不能以“国内少见”“换成中文数据”“本科要求低”代替最近工作的比较。研究型本科论文也可贡献严谨的复现、适配和适用边界实证，是否达到学院标准应由导师按实际证据判断。
