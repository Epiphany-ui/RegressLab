# v2 研究资料与导入说明

本目录是用户提供的`regresslab-research-v2`研究方案。8份Markdown在`source/`中逐字节保留，导入摘要见[import-manifest.json](import-manifest.json)。这些原文的实验、文献和审查状态属于来源陈述，不会因为复制入仓库而变成新的实验结果。

当前论文主线是**历史群体风险驱动的文本分类回归测试选样**。四版链f0→f1→f2→f3；已有历史形成参考正确池，先冻结全部套件再解封目标。HGC是待验证方法，旧启发式是基线，原型只支撑复现与展示。

| 原文 | 内容 |
|---|---|
| [源包入口](source/README.md) | 研究方向和与旧方案的关系 |
| [研究定位](source/01-research-position.md) | RQ1—RQ3、贡献和论文边界 |
| [文献地图](source/02-literature-map.md) | 相邻方法、访问条件与待复现项 |
| [算法方案](source/03-algorithm-spec.md) | 历史风险、饱和覆盖、代表性和开发配置 |
| [实验协议](source/04-experiment-protocol.md) | 数据/四版链、强基线、统计、成本和G0—G3 |
| [范围与计划](source/PRODUCT.md) | 研究原型的软件作用与阶段安排 |
| [教师摘要](source/05-teacher-brief.md) | 可用的Markdown讨论材料 |
| [来源审查记录](source/06-review-and-verification.md) | 来源声称的查阅与未执行项 |

源README引用了`研究方向调整方案简述.docx`，本次提供的目录内没有该文件；保留原文并在清单中记录一个已知缺失链接，未生成或冒充已经检查过的Word。需要沟通时可使用上表的Markdown教师摘要。

源PRODUCT所述Demo提交`a702894`与任务开始时本地`46f4ed4`不同；同步时已实际拉取并确认它是远端main的提交，将保留其历史和文案修改。来源所称的测试仍不直接充当本次验收，本轮另行运行兼容测试。本次新增的工程补充见[软件设计与开发计划](../../engineering/v2/README.md)。旧应用方案留在[归档](../../archive/v1.3/README.md)。
