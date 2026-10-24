# 当前实现状态与下一步

当前权威是[研究v2](../research/v2/README.md)与[工程v2](../engineering/v2/README.md)。原产品优先路线已移入[v1.3历史记录](../archive/v1.3/development/IMPLEMENTATION.md)；PostgreSQL、复杂任务和完整Ollama不再是下一阶段前置条件。

| 内容 | 实际状态 |
|---|---|
| 0.1 Demo | 已实现：严格导入/对齐、成对指标、净下降候选、D案例、SQLite历史、HTML/JSON导出 |
| v1夹具/测试 | 保留：两份预测、50/25/25分区、固定旧门槛；只验证工程流程 |
| v2研究原文 | 已导入8份并记录摘要，未补造缺失Word或沿用来源提交的验收结论 |
| v2工程设计 | 本次补齐架构、领域/工件Schema、信息隔离/冻结、成本、Demo迁移、测试和分阶段任务 |
| experiments/preflight | 原两轮＋固定可行性收尾已完成：200机制环境/14,400单元，独立CLINC审计与24新模型/6链/2,088单元，Risk-Top/HGC/基线及完整审计 |
| 新增历史增量检验 | 已完成：同Scaler/LR的margin1维对照与历史6维设计、整链LOCO、12留出链/64新模型/1,152单元、独立复核 |
| 当前任务模型 | 字符TF-IDF＋LR/SGD，以及CPU词嵌入均值＋64维MLP；真实神经资源和有限链已运行，未做Transformer/LLM/LoRA训练 |
| lab | 统一包仍为规划；HGC归档；preflight已实现Risk-LR分数版诊断适配，Behavior-Anchor/Grad-PD/完整消融仍未完成 |
| v2研究结果展示 | 已规划只读接口和工件页面；当前UI/API尚未实现 |
| 真实结果 | HGC NO_GO并归档；新神经增长链B100均净+5例、平均Recall+7.88个百分点，通过单格筛查；未跨架构复现，总成本优势未建立 |

最新为[历史增量检验](../experiments/history-increment-v1/README.md)、[本阶段日志](logs/2026-10-24-history-increment.md)与[新机器决策](../experiments/history-increment-v1/decision.json)：`CONDITIONAL_SIGNAL_REQUIRES_REPLICATION`。代码与协议事前提交`cd07b1d`，新目标在12链全矩阵冻结后曝光，288项测试通过；131冻结文件、新64/旧72状态、98事件重放与4类故障拒绝。CLINC VAL样本已曝，只称未见更新；TEST封存。此前[HGC收尾](../experiments/feasibility-closeout/README.md)、[第二轮](../experiments/cpu-preflight-v2/README.md)和[首轮](../experiments/cpu-preflight-v1/README.md)保留原状。

HGC继续归档；下一道问题应收窄到小神经数据增长条件的独立复核，先检验复现与总成本，不能把本轮更替B50改作主结果或据此定题。没有自动新增运行或HGC搜索。正式G0—G3、GPU训练/峰值显存实测、完整核心方法与研究页面仍未完成；原研究文档未改写。

当前`domain.py`的严格JSON解析和成对计数可以提取复用；分区、D+C scope、净下降筛选、特征及候选池含义不能原样变成HGC。每个替换点和下一版最小Demo见[迁移设计](../engineering/v2/05-demo-migration.md)。

具体文件、接口、计划命令、测试和G0—G3验收见[07实施计划](../engineering/v2/07-implementation-plan.md)。`preflight`是开发用小入口，不等于已交付全部P0—P3通用框架；软件测试通过不证明研究方法有效。
