# 真实模型准备：计划目录

本目录目前只有工作边界说明，**尚无训练/推理代码、依赖锁或模型效果结果**。

未来包名`regresslab_experiments`，与Web和lab环境分开锁定。计划包括MASSIVE/CLINC150适配、TRAIN-only CPU四版更新、0.6B LoRA资源试验、受登记scope约束的推理、完整类别分数适配及真实来源/硬件/运行清单。

模型训练与选择方法开发是两类工作。实验准备器可以生成f3权重，但主selector不能读取f3；其完整预测须按冻结协议封存并由独立评测器解封。不能沿用旧三检查点配方声称已经形成四版链。GPU初始20小时护栏和实际配方均需开发试验登记。

计划命令前缀`python -m regresslab_experiments.cli`当前不可执行。开发任务见[实施计划](../docs/engineering/v2/07-implementation-plan.md)，来源要求见[数据合同](../docs/engineering/v2/03-domain-data-contracts.md)。数据与权重分别写入Git排除的`datasets/`、`checkpoints/`，不上传模型权重到Web。
