# 文档入口

当前软件是 0.1.0 描述性 Demo。完整产品的 1.3 设计基线单独保存在 `specs/`；其中的未来任务、部署命令和“尚未实现”描述属于设计阶段，不表示当前 Demo 的实际运行状态。

| 分类 | 入口 | 适合查什么 |
|---|---|---|
| 当前 Demo | [实现与后续里程碑](development/IMPLEMENTATION.md)、[Demo API](development/DEMO-API.md) | 已实现范围、与完整成品的差异、当前接口 |
| 运行与验收 | [仓库启动说明](../README.md)、[应用验证记录](quality/VALIDATION.md)、[合成夹具](../examples/README.md) | 启动、实测结果、精确核对值和截图 |
| 完整产品设计 | [设计总目录](specs/README.md)、[产品定义](specs/PRODUCT.md)、[实施计划](specs/12-implementation-plan.md) | 毕设完整范围、需求、算法、实验和后续任务 |
| 界面约定 | [工作台设计规范](design/DESIGN.md) | 配色、层级、响应式与无障碍目标 |
| 机器合同 | [合同与夹具目录](contracts/README.md) | 完整产品的 OpenAPI、DDL、JSON Schema 和算法金标准 |
| 设计验证历史 | [设计静态检查记录](verification/README.md) | 原设计的检查范围、输出和未执行项 |

建议先读当前实现与应用验证记录，再按需查看 Demo API 和合成夹具。继续开发完整系统时，从产品定义进入设计总目录，依次阅读数据/算法协议、模型版本协议及实施计划。

应用测试与设计静态检查分别记录。合成夹具、合同通过和页面可运行都不等于真实模型训练、独立确认或研究效果已验证。教师材料保存在 [Word 简版](specs/teacher-brief.docx)。

文档路径以当前目录为基准；启动和验证命令如无特别说明，在仓库根目录执行。设计静态检查入口为 `node scripts/check-design.cjs`。
