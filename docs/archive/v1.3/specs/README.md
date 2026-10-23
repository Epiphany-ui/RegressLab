# 大模型分类应用退化诊断与回归测试系统开发文档包

版本1.3 · 2026年10月22日 · 正式开发期2027年1—4月。

**论文题目：面向大模型分类应用的退化诊断与回归测试系统的设计与实现。论文按应用开发类规划，具体登记由学院确认。**

本目录保存2026年10月22日的1.3完整产品设计基线，配套机器合同和设计验证分别位于相邻目录。用户已确认：小型开源语言模型真实微调更新为主实验，逻辑回归重新训练为对照，API选做。形成此基线时尚未完成真实训练、GPU资源、应用运行和研究效果验收；当前Demo进展见[实现说明](../development/IMPLEMENTATION.md)和[应用验证记录](../../../quality/VALIDATION.md)，文档统一入口见[上级目录](../README.md)。

先读[PRODUCT](PRODUCT.md)理解完整成品，再读[19模型版本生成](19-model-version-protocol.md)回答“旧版从哪来、新版怎么修改”。发老师使用[Word简版](teacher-brief.docx)；PDF仅在实际生成并核验后附在本目录，不沿用旧在线转换链接。

## 核心范围

- 固定标签文本分类/意图识别，MASSIVE1.1 zh-CN及公开gold；不做开放回答或视觉评测。
- Qwen3-0.6B TRAIN-only LoRA的预定检查点v1/v2/v3为主版本链；6GB显存可行性先测，不保证效果。
- TF-IDF＋逻辑回归CPU重新训练对照；Ollama已安装模型原生推理；外部微调模型同后端真实推理导入。
- FastAPI＋Vue3/TypeScript、PostgreSQL、单Worker、Docker Compose、中文界面、版本/任务/报告/恢复闭环。
- 成对比较、D分组、合格证据的一次C、审查、预算精选、冻结套件、后续版本真实重放。
- API分类、其他规模/语言和微调模型转Ollama为P1；旧解释接口关闭兼容，不列开发计划。

“第一版/P0”指最终毕业成品；前期Demo只是部分流程。硬件按用户说明为桌面端3060、6GB显存。2026年10月下旬—11月中旬Demo暂估累计8—12小时，11月下旬—12月备考优先。

## 导航

| 文件 | 用途 |
|---|---|
| [PRODUCT](PRODUCT.md) / [00](00-project-charter.md) | 产品全貌、范围、价值、可行性和风险 |
| [01](01-requirements.md) / [02](02-domain-workflows.md) | 需求、对象、状态、事务和边界 |
| [03](03-data-protocol.md) / [04](04-algorithms.md) | 数据/版本/预测合同及指标、分组、精选算法 |
| [05](05-architecture.md) / [06](06-database.md) / [07](07-api.md) | 架构、DDL、HTTP和机器合同 |
| [08](08-ui-spec.md) / [09](09-test-plan.md) | 页面、异常、软件测试和成品验收 |
| [10](10-deployment-security.md) / [13](13-user-operations.md) | 部署、宿主机Ollama、备份、用户与答辩流程 |
| [11](11-experiment-protocol.md) / [17](17-baselines-and-algorithm-evolution.md) | 正式实验、五基线两消融、开发调整与停止规则 |
| [12](12-implementation-plan.md) | 任务、文件、接口、验证命令及阶段出口 |
| [14](14-traceability-review.md) / [18](18-revision-notes.md) | 需求追踪、漏洞修订、评审与版本记录 |
| [15](15-sources-decisions.md) / [16](16-proposal-summary.md) | 一手来源及教师开题摘要 |
| [19](19-model-version-protocol.md) | 真实修改、检查点、训练/推理准备、资源和冻结顺序 |
| [机器合同](../contracts/README.md) / [验证记录](../verification/README.md) | OpenAPI、DDL、Schema、样例和静态检查边界 |

## 开发顺序和证据边界

按12执行，先环境/数据，再19小模型资源与输出预实验，再版本/预测/诊断/套件/UI和恢复。0.6B微调失败须明确记录，不能以逻辑回归冒称完成主验证。训练环境独立锁定，不开发网页大模型训练平台。

先通过合成工程夹具，再运行真实数据。预测100%合法覆盖才允许统计；所有原始响应与run身份可追溯，不拼接不同LLM运行。DEV100例×3稳定性门槛不通过时只描述D、不确认；来源DECLARED不因hash合法变成真实训练认证。

固定初版选择策略为默认，所有方法共用池、预算和后续目标；训练链、检查点、样本和selector随机seed不是同一独立单位。未来预测在套件冻结后生成/解封；无退化、无分组或无增益如实报告。不把“未发现”当安全，不承诺创新或发表。

文档静态检查、示例合法和独立设计审阅仅证明相应检查范围；不能证明6GB训练、真实统计功效、产品部署和效果已经通过。锁文件、源文件hash及实测结果在开发时记录，不预造。
