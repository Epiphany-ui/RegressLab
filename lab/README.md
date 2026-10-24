# 离线研究核心：计划目录

本目录目前只有架构说明，**尚无可执行的研究包或算法**。当前可运行Demo在`backend/`和`frontend/`。

实际离线研究代码目前在[experiments/preflight](../experiments/README.md)，已有CPU基线、归档HGC、同预测器历史增量检验与小神经链；不能把本目录仍为计划理解为这些实验尚未执行。当前结论与下一阶段边界见[历史增量报告](../docs/experiments/history-increment-v1/README.md)。

未来包名`regresslab_lab`，独立环境/真实锁文件将在第一项实现任务中创建。职责是数据/历史工件验证、共同P、方法登记与访问分层、群体风险、统一基线/HGC、套件及完整矩阵冻结、独立目标评测、成本/统计及视图bundle。不得把GPU训练或Web任务调度混入纯selector。

计划命令前缀为`python -m regresslab_lab.cli`，当前不可执行；子命令和任务见[实施计划](../docs/engineering/v2/07-implementation-plan.md)，接口见[架构](../docs/engineering/v2/02-architecture.md)。

研究工件默认写入Git排除的`artifacts/research-v2/`；目标输出放在独立封存根目录。所有任务以[研究v2](../docs/research/v2/README.md)为依据。
