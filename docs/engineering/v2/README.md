# v2 工程设计与开发计划

当前权威：研究v2；状态：`research-v2-draft1`软件设计。Web仍为0.1描述性Demo；已通过独立`preflight`入口完成[两轮CPU开发预实验](../../experiments/cpu-preflight-v2/README.md)，固定最小HGC未显示收益。通用lab、其余核心方法、神经训练与研究API仍待实现；正式实验门禁尚未通过，当前停止同DEV继续寻优，最新优先级见07。

| 文档 | 用途 |
|---|---|
| [01 范围与决策](01-scope-and-decisions.md) | v1→v2差异、当前/计划/暂缓、需要在正式实验前冻结的决定 |
| [02 架构](02-architecture.md) | 离线研究、独立训练、只读工作台、目录和恢复边界 |
| [03 领域与合同](03-domain-data-contracts.md) | 身份、分区、四版历史、工件与数据持久化 |
| [04 工作流与成本](04-workflow-and-costs.md) | 输入隔离、方法访问层、全矩阵冻结、评测与两本成本账 |
| [05 Demo演进](05-demo-migration.md) | 现有代码复用边界、计划中的研究接口与页面 |
| [06 验收设计](06-validation-plan.md) | 单元、合同、集成、泄漏与重现性测试，研究结论边界 |
| [07 实施计划](07-implementation-plan.md) | 分阶段文件/接口/命令/依赖、G0—G3出口、下一轮任务 |
| [合同草案](contracts/README.md) | 机器可读工件Schema；不是现有Demo API或已实现研究协议 |

阅读顺序：先看[研究原文入口](../../research/v2/README.md)，再读01/02/07，需要实现某一阶段时查03—06及合同。当前Demo的实际接口见[兼容说明](../../development/DEMO-API.md)。
