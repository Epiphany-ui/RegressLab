# 当前实现状态与下一步

当前权威是[研究v2](../research/v2/README.md)与[工程v2](../engineering/v2/README.md)。原产品优先路线已移入[v1.3历史记录](../archive/v1.3/development/IMPLEMENTATION.md)；PostgreSQL、复杂任务和完整Ollama不再是下一阶段前置条件。

| 内容 | 实际状态 |
|---|---|
| 0.1 Demo | 已实现：严格导入/对齐、成对指标、净下降候选、D案例、SQLite历史、HTML/JSON导出 |
| v1夹具/测试 | 保留：两份预测、50/25/25分区、固定旧门槛；只验证工程流程 |
| v2研究原文 | 已导入8份并记录摘要，未补造缺失Word或沿用来源提交的验收结论 |
| v2工程设计 | 本次补齐架构、领域/工件Schema、信息隔离/冻结、成本、Demo迁移、测试和分阶段任务 |
| lab与experiments | 只有目录职责说明，尚无研究算法/训练包或可运行命令 |
| v2研究结果展示 | 已规划只读接口和工件页面；当前UI/API尚未实现 |
| 真实研究结果 | 未完成CPU四版链、神经迁移、HGC对照、正式目标解封和统计/成本结论 |

后续优先交付：来源可追溯的v2数据与四版历史合同 → HistoryView/共同P/登记及冻结骨架 → 真实CPU链和统一强基线 → HGC/机制模拟/开发冻结 → 正式评价与只读证据浏览。GPU资源预实验在G0及早做，能否扩展按实测决定。

当前`domain.py`的严格JSON解析和成对计数可以提取复用；分区、D+C scope、净下降筛选、特征及候选池含义不能原样变成HGC。每个替换点和下一版最小Demo见[迁移设计](../engineering/v2/05-demo-migration.md)。

具体文件、接口、计划命令、测试和G0—G3验收见[07实施计划](../engineering/v2/07-implementation-plan.md)。本轮是开发规划，不把“有Schema”或“页面可运行”当作方法已经完成。
