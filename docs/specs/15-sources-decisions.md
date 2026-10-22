# 来源、相近工作与决策登记

检索核验日期：2026-10-22。只引用论文、作者/项目官方仓库、官方数据卡及工具文档。已读到的材料不等于代码已执行；没有声称复现论文指标。网页和软件到2027年可能变化，开发开始须记录实际版本。

| 编号 | 来源 | 对本设计的作用 |
|---|---|---|
| S01 | [Regression Bugs Are In Your Model! ACL2021](https://aclanthology.org/2021.acl-long.515/) | negative flip与NLP更新退化已有定义；不是本项目创新 |
| S02 | [MASSIVE作者仓库](https://github.com/alexa/massive) | 原始JSONL、版本、平行id、下载与建模来源 |
| S03 | [MASSIVE官方数据卡](https://huggingface.co/datasets/AmazonScience/massive) | gold意图/槽位、许可与字段；记录数量不一致和加载脚本失效提示 |
| S04 | [SliceLine作者论文](https://mboehm7.github.io/resources/sigmod2021b_sliceline.pdf)、[实现](https://github.com/DataDome/sliceline) | 自动弱分组搜索已存在，作为强基线；实现BSD-3-Clause |
| S05 | [Deepchecks WeakSegmentsPerformance](https://docs.deepchecks.com/stable/api/generated/deepchecks.tabular.checks.model_evaluation.WeakSegmentsPerformance.html)、[JMLR2022论文](https://www.jmlr.org/papers/volume23/22-0281/22-0281.pdf) | 分组性能诊断与ML测试工具已有系统；不能把完整流程界面当唯一创新 |
| S06 | [Certifying Model Upgrades with Slice-Wise Non-Regression and Incumbent Fallback，2026-09](https://arxiv.org/abs/2609.13714) | 区分没发现伤害与认证非劣；本系统只做退化确认，不复刻其认证保证；论文实验也未建立基础大模型升级收益 |
| S07 | [SciPy binomtest](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html) | 单侧精确二项检验API；应用于成对discordance |
| S08 | [statsmodels multipletests](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html) | Holm修正对照实现 |
| S09 | [sklearn Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) | 训练/评测边界、预处理拟合不得泄漏 |
| S10 | [sklearn Model persistence](https://scikit-learn.org/stable/model_persistence.html) | 不可信pickle代码执行风险；只加载内部受信产物 |
| S11 | [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) | 长计算与API进程分离的工程判断；本项目选择持久worker |
| S12 | [PostgreSQL16 SELECT](https://www.postgresql.org/docs/16/sql-select.html)、[锁](https://www.postgresql.org/docs/16/explicit-locking.html) | SKIP LOCKED队列、短事务与CAS实现依据 |
| S13 | [Node.js Releases](https://nodejs.org/en/about/previous-releases) | Node24在核验时为LTS；具体patch由开发锁文件记录 |
| S14 | [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/) | 可选说明的JSON格式与实际用量；不锁定未来价格 |
| S15 | [Apple MUSCLE，2024](https://machinelearning.apple.com/research/model-compatibility) | 模型升级兼容性与训练缓解已有研究；本系统不主张训练算法创新 |
| S16 | [ELKI GreedyKCenter官方文档](https://elki-project.github.io/releases/current/doc/elki/clustering/kcenter/GreedyKCenter.html)、[Gonzalez1985原论文](https://doi.org/10.1016/0304-3975(85)90224-5) | 最远点选择已有；本设计在TF-IDF空间构造对照，不移用其理论保证到未来退化检出 |
| S17 | [sklearn StratifiedShuffleSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedShuffleSplit.html) | 标签分层抽样思想；17自行明确定额与B小于类别数规则，不冒称复现库的随机输出 |
| S18 | [TF-IDF](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)、[余弦距离](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_distances.html) | 字符表示与距离；不是语义或根因金标准 |

## 最近工作对照

| 相近工作 | 已有能力 | 本设计可实现的不同侧重 | 尚不能宣称的内容 |
|---|---|---|---|
| S01/S15 | 定义/测量退化，训练减少负翻 | 面向维护者的诊断与冻结套件工作流 | 首次发现模型升级退化 |
| S04 | 弱分组枚举/优化 | 成对净退化目标+固定C确认+套件精选 | 自动找分组或覆盖贪心本身新颖 |
| S05 | ML测试、弱分组、报告 | 有明确一次确认和跨版本套件成本核算 | 第一个模型测试平台 |
| S06 | 独立成对评价与非劣协议 | 应用开发工具，只显示确认退化/不足 | 有相同安全认证保证、独立验证首创 |

拟议精选策略的跨未来版本收益尚未确认，需按11检验。国内空白没有充分证据，不写进开题承诺。不承诺论文发表或优于所有现有工具。

## 用户决定与设计者决定

用户决定：选择题目1做详细文档；单人辅助编码；2027年1—4月；FastAPI/Vue/TS；6GB3060；第一版评测范围由助手判断；学院无特殊要求。

设计者决定：分类而非开放生成；小型语言模型微调主验证、CPU重新训练对照；PostgreSQL16；单worker；固定5种输入特征；D/C/A按组件hash划分；最深2项合取；20个候选；精确单侧检验+Holm；支持40、效应0.05；不做非劣认证；无API可完整运行；单令牌；API分类可选，旧解释兼容接口默认关闭且不列开发计划。

实施时可自行决定：非关键CSS、内部私有函数、SQLAlchemy查询写法、日志库、单元测试文件内组织。不得自行改变：标签、分区、统计方向/阈值、候选冻结、gold用途、scope语义、终态与费用口径；这类变更须ADR、合同和测试同步修订。

## 仍待实际运行验证

原始文件实际数量/hash、0.6B微调在6GB下的可行性、完整提示长度、稳定性、训练自然退化规模、CPU/GPU耗时及显存/RAM、统计功效、精选相对强基线收益、依赖锁兼容、真实部署恢复、DeepSeek未来型号/费用。它们是执行阶段需要测量的事实，不是文档中缺失的任意业务选择。

## 1.1补充决定与未证实事项

五种选择基线、两消融和可选优先级对照见17；这使初轮比较更完整，不等于穷尽最近同类回归测试选择论文。贪心框架和组成因素不主张原创。1000/10是排序编码，2:1权重及覆盖优先是假设；开发晋级门槛也只是预先制定的工程标准。

用户本轮授权补齐基线与算法调整文档，没有授权产品实现。生产coverage_diversity_v1、API和DDL不变；后续策略只能先在lab开发，冻结后评价，晋级生产须另行版本修订。


## 1.3核验来源与范围变更

截至2026年10月22日核验以下一手资料；未运行对应实现，不以模型卡宣传成绩代替本任务实测。

| 编号 | 官方来源 | 支持什么及不能推断什么 |
|---|---|---|
| S19 | [Qwen3-0.6B模型卡](https://huggingface.co/Qwen/Qwen3-0.6B) | 公开权重、许可、Transformers使用入口；不证明本地6GB训练或分类效果 |
| S20 | [PEFT LoRA](https://huggingface.co/docs/peft/v0.21.0/package_reference/lora) | 参数高效微调已有；本项目不发明LoRA，具体资源和配方须测 |
| S21 | [PEFT量化训练](https://huggingface.co/docs/peft/main/en/developer_guides/quantization) | QLoRA可作为开发期替代方案；文档示例显存不等于本设备保证 |
| S22 | [Ollama模型列表接口](https://docs.ollama.com/api/tags) | digest与模型/量化元数据，登记已安装版本 |
| S23 | [Ollama结构化输出](https://docs.ollama.com/capabilities/structured-outputs) | JSON Schema约束；格式正确不保证标签正确 |
| S24 | [Ollama资源说明](https://docs.ollama.com/faq) | 上下文/CPU-GPU加载检查；文件大小不等于峰值显存 |
| S25 | [Ollama导入](https://docs.ollama.com/import) | Safetensors/GGUF导入路径；不保证当前Qwen3 LoRA直接兼容 |
| S26 | [LogisticRegression参数](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) | 可调正则化并重新训练；不属于LLM规模曲线中的一个小参数点 |
| S27 | [PyTorch复现说明](https://pytorch.org/docs/stable/notes/randomness.html) | 固定seed不保证跨平台/版本完全复现，确定性控制仍需实测 |

用户已确认：真实小模型微调为主、逻辑回归保留对照、API选做，授权同步整包。默认Qwen3-0.6B、步数100/200/300、LoRA配方和证据资格为设计者选择，尚未经实测，不冒称用户指定或最优。普通API不能通过本地调参直接改厂商权重；API访问方式与是否开放权重分开记录。未知规模不填猜测参数量。

本次版本1.3新增实际修改链、模型与run身份、原始响应、稳定性证据和描述降级；生产选择算法及统计阈值未晋级。算法收益、真实功效及最新近邻选择方法的新颖性仍未确认。S06的公开摘要再次核对，不把其非劣认证或模拟结论移植为本系统保证。
