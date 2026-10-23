# v1.3 应用方案归档

状态：**历史设计，已由研究v2取代**。本目录保留原题目、应用功能、三版实验、50/25/25分区、PostgreSQL/Worker和旧选择策略的追溯资料，不能作为新的研究验收要求。

当前权威入口：[研究v2](../../research/v2/README.md)、[工程v2](../../engineering/v2/README.md)。现有0.1 Demo仍沿用其中部分规则，运行/API说明见[Demo兼容接口](../../development/DEMO-API.md)。

| 资料 | 入口 |
|---|---|
| 原规格与教师材料 | [specs/README.md](specs/README.md) |
| 原机器合同与夹具 | [contracts/README.md](contracts/README.md) |
| 原静态检查记录 | [verification/README.md](verification/README.md) |
| 原后续产品路线 | [development/IMPLEMENTATION.md](development/IMPLEMENTATION.md) |

从仓库根目录执行`node scripts/check-legacy-design.cjs`仅检查本历史包的17项静态约束；它不评价HGC、v2研究合同或当前实验效果。
