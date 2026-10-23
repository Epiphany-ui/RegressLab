# 当前实现状态与下一步

当前权威是[研究v2](../research/v2/README.md)与[工程v2](../engineering/v2/README.md)。原产品优先路线已移入[v1.3历史记录](../archive/v1.3/development/IMPLEMENTATION.md)；PostgreSQL、复杂任务和完整Ollama不再是下一阶段前置条件。

| 内容 | 实际状态 |
|---|---|
| 0.1 Demo | 已实现：严格导入/对齐、成对指标、净下降候选、D案例、SQLite历史、HTML/JSON导出 |
| v1夹具/测试 | 保留：两份预测、50/25/25分区、固定旧门槛；只验证工程流程 |
| v2研究原文 | 已导入8份并记录摘要，未补造缺失Word或沿用来源提交的验收结论 |
| v2工程设计 | 本次补齐架构、领域/工件Schema、信息隔离/冻结、成本、Demo迁移、测试和分阶段任务 |
| experiments/preflight | 已实现独立锁定的CPU开发预实验：官方数据下载/清理、24模型、6条四版链、9基线、全矩阵文件冻结、DEV_SELECTOR评分与工件复核 |
| lab | 仍为职责/架构规划；统一HistoryView、HGC、Risk-LR、Behavior-Anchor和Grad-PD尚未实现 |
| v2研究结果展示 | 已规划只读接口和工件页面；当前UI/API尚未实现 |
| 真实结果 | 首轮CPU预实验已完成，每链5—9翻转；跨链等价节点、稀疏信号和缺类限制正式资格。神经迁移、HGC对照、正式评价及统计/成本结论均未完成 |

本轮先按用户纠正完成真实预实验，记录见[报告](../experiments/cpu-preflight-v1/README.md)和[开发日志](logs/2026-10-23-cpu-preflight.md)。CPU可运行、每家族3条链有非零翻转，仅满足登记的机械信号规则，**不表示G0/G1整体通过**；实际探测为RTX 3060 Laptop 6GiB，尚未跑GPU资源试验。

接下来优先：登记前核对跨链模型的语义身份、修订独立链配置 → 复核DEV类别支持、稀疏信号和独立外部数据 → 补每方法可比成本 → 再决定HGC最小实现和机制试验。GPU资源试验、正式冻结和只读证据浏览仍按研究门禁进入，暂不以平台/UI建设取代预实验。

当前`domain.py`的严格JSON解析和成对计数可以提取复用；分区、D+C scope、净下降筛选、特征及候选池含义不能原样变成HGC。每个替换点和下一版最小Demo见[迁移设计](../engineering/v2/05-demo-migration.md)。

具体文件、接口、计划命令、测试和G0—G3验收见[07实施计划](../engineering/v2/07-implementation-plan.md)。`preflight`是开发用小入口，不等于已交付全部P0—P3通用框架；软件测试通过不证明研究方法有效。
