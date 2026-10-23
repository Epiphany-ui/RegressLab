# 文档导航：当前研究 v2

当前主线由“应用系统开发”转为“历史群体风险驱动的回归测试选样研究”。软件仍是0.1描述性Demo；本次交付v2工程设计和开发规划。真实模型链、HGC/强基线实现、目标冻结评测与效果实验尚未完成。

| 类别 | 入口 | 状态与用途 |
|---|---|---|
| 研究依据 | [研究v2](research/v2/README.md) | 用户提供8份原文、来源hash和已知缺失附件；科学问题/算法/实验 |
| 当前开发计划 | [工程v2总目录](engineering/v2/README.md)、[分阶段任务](engineering/v2/07-implementation-plan.md) | 本轮补齐：架构、模块、工件/数据、工作流、Demo迁移、测试和出口 |
| 当前代码事实 | [实施状态](development/IMPLEMENTATION.md)、[现有Demo API](development/DEMO-API.md) | 已实现的v1兼容软件，不等于v2实验实现 |
| 运行与小夹具 | [仓库README](../README.md)、[examples](../examples/README.md) | 可启动演示与历史工程夹具 |
| 质量证据 | [Demo历史验收](quality/VALIDATION.md)、[本轮规划验收](quality/V2-PLANNING-VALIDATION.md) | 分开记录代码测试、文档/schema检查和未执行实验 |
| 视觉约定 | [DESIGN](design/DESIGN.md) | 沿用设计体系，未来增加研究证据视图 |
| 历史方案 | [v1.3归档](archive/v1.3/README.md) | 原规格/合同/实验及旧产品路线，仅追溯，不再支配v2开发 |

建议阅读：研究定位/算法/实验协议 → 工程01范围与02架构 → 07实施计划 → 按任务查03合同、04工作流、05界面迁移、06验收。科学参数尚未冻结的事项集中在[决策清单](engineering/v2/01-scope-and-decisions.md)。

当前文档检查：从仓库根目录执行`backend/.venv/bin/python scripts/check-docs.py`。它核对8份来源的完整性、所有本地文档目标及v2 Schema草案；源Word未提供的链接单独列为已知警告。`node scripts/check-legacy-design.cjs`只验证历史合同包，不是v2实验测试。
