# 当前实现状态与下一步

当前权威是[研究v2](../research/v2/README.md)与[工程v2](../engineering/v2/README.md)。原产品优先路线已移入[v1.3历史记录](../archive/v1.3/development/IMPLEMENTATION.md)；PostgreSQL、复杂任务和完整Ollama不再是下一阶段前置条件。

| 内容 | 实际状态 |
|---|---|
| 0.1 Demo | 已实现：严格导入/对齐、成对指标、净下降候选、D案例、SQLite历史、HTML/JSON导出 |
| v1夹具/测试 | 保留：两份预测、50/25/25分区、固定旧门槛；只验证工程流程 |
| v2研究原文 | 已导入8份并记录摘要，未补造缺失Word或沿用来源提交的验收结论 |
| v2工程设计 | 本次补齐架构、领域/工件Schema、信息隔离/冻结、成本、Demo迁移、测试和分阶段任务 |
| experiments/preflight | 已完成两轮CPU开发预实验；第二轮24模型/6链、9基线＋固定HGC、全局推理身份门禁、2,064单元冻结、完整P与每方法成本复核 |
| 当前任务模型 | 字符TF-IDF＋多类逻辑回归；HGC为选样算法，不是替代分类模型 |
| lab | 统一包仍为规划；HGC已在preflight中最小实现，Risk-LR、Behavior-Anchor、Grad-PD及完整机制/消融尚未完成 |
| v2研究结果展示 | 已规划只读接口和工件页面；当前UI/API尚未实现 |
| 真实结果 | 第二轮目标身份门禁通过；每链2—11翻转，HGC@100 Recall=0—.50、margin=.80—1；缓存情景HGC成本为全P推理11—15倍。三项开发筛查未通过，非正式结论 |

最新[第二轮报告](../experiments/cpu-preflight-v2/README.md)和[2026-10-24开发日志](logs/2026-10-24-cpu-preflight-v2.md)记录负结果，首轮发现保留在[原报告](../experiments/cpu-preflight-v1/README.md)。两轮上限已到，不继续同DEV的lambda/m、特征或seed寻优；正式G0/G1/G2均不能据此标通过。GPU仅探测到RTX 3060 Laptop 6GiB，没有训练/显存实测。

接下来优先整理研究决策材料，开展事前固定的最小风险迁移机制诊断与独立外部数据的来源/类别审计。若缺少支持，收缩为强基线比较或适用条件研究；不得把扩大GPU、平台或UI当作当前方法证据的替代。完整核心方法、独立外部/留出评价、神经迁移与研究结果页面均未完成。

当前`domain.py`的严格JSON解析和成对计数可以提取复用；分区、D+C scope、净下降筛选、特征及候选池含义不能原样变成HGC。每个替换点和下一版最小Demo见[迁移设计](../engineering/v2/05-demo-migration.md)。

具体文件、接口、计划命令、测试和G0—G3验收见[07实施计划](../engineering/v2/07-implementation-plan.md)。`preflight`是开发用小入口，不等于已交付全部P0—P3通用框架；软件测试通过不证明研究方法有效。
