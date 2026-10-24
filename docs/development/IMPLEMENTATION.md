# 当前实现状态与下一步

当前权威是[研究v2](../research/v2/README.md)与[工程v2](../engineering/v2/README.md)。原产品优先路线已移入[v1.3历史记录](../archive/v1.3/development/IMPLEMENTATION.md)；PostgreSQL、复杂任务和完整Ollama不再是下一阶段前置条件。

| 内容 | 实际状态 |
|---|---|
| 0.1 Demo | 已实现：严格导入/对齐、成对指标、净下降候选、D案例、SQLite历史、HTML/JSON导出 |
| v1夹具/测试 | 保留：两份预测、50/25/25分区、固定旧门槛；只验证工程流程 |
| v2研究原文 | 已导入8份并记录摘要，未补造缺失Word或沿用来源提交的验收结论 |
| v2工程设计 | 本次补齐架构、领域/工件Schema、信息隔离/冻结、成本、Demo迁移、测试和分阶段任务 |
| experiments/preflight | 原两轮＋固定可行性收尾已完成：200机制环境/14,400单元，独立CLINC审计与24新模型/6链/2,088单元，Risk-Top/HGC/基线及完整审计 |
| 当前任务模型 | 字符TF-IDF＋LR及SGD log-loss线性分类器；增加优化/概率链接对照，未做神经或大语言模型训练；HGC仅为选样算法 |
| lab | 统一包仍为规划；HGC已在preflight中最小实现，Risk-LR、Behavior-Anchor、Grad-PD及完整机制/消融尚未完成 |
| v2研究结果展示 | 已规划只读接口和工件页面；当前UI/API尚未实现 |
| 真实结果 | 当前HGC NO_GO；模拟定位覆盖过早饱和，独立CLINC增长Risk-Top有受限正线索但margin更强；事件支持量不足，不建立普遍或正式结论 |

最新[预实验收尾报告](../experiments/feasibility-closeout/README.md)、[收尾日志](logs/2026-10-24-feasibility-closeout.md)和[机器决策](../experiments/feasibility-closeout/decision.json)已形成完整投入建议。原[第二轮](../experiments/cpu-preflight-v2/README.md)及[首轮](../experiments/cpu-preflight-v1/README.md)保留追溯；首轮没有HGC，不能把两次CPU试跑说成HGC已充分开发。本次用户授权一次固定机制/独立数据收尾，未调HGC参数，现已结束。

建议停止当前覆盖式HGC的优势新方法路线，保留广义历史风险问题作为有条件的比较/机制研究候选。若论文要求稳定超过强基线的新算法，应先调整具体研究主张。正式G0—G3、神经训练/显存实测、完整核心方法与研究页面均未完成，不自动沿旧计划扩规模。原研究文档和题目未擅自改写。

当前`domain.py`的严格JSON解析和成对计数可以提取复用；分区、D+C scope、净下降筛选、特征及候选池含义不能原样变成HGC。每个替换点和下一版最小Demo见[迁移设计](../engineering/v2/05-demo-migration.md)。

具体文件、接口、计划命令、测试和G0—G3验收见[07实施计划](../engineering/v2/07-implementation-plan.md)。`preflight`是开发用小入口，不等于已交付全部P0—P3通用框架；软件测试通过不证明研究方法有效。
