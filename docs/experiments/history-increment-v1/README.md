# 历史信息对margin的增量检验

本阶段承接用户明确提出的四步建议：[归档HGC](../HGC-ARCHIVE.md)、同预测器增量检验、整条未见更新验证，以及先资源后有限链的小神经模型实验。它进一步检验研究问题，不通过改题目认定选题已经解决。

事前设计见[登记协议](REGISTRATION.md)、[机器配置](../../../experiments/configs/history-increment-v1.json)与[相邻研究](RELATED-WORK.md)。全部已见结果属于开发材料，CLINC VAL文字已经曝光，正式TEST继续封存。新留出为两架构、两更新条件各3条四版本链；新增4条神经开发链只负责定参。HGC只保留原风险估计的一列，不修改其分组公式或继续运行覆盖优化。

## 复现与工件约定

主实验和独立复核使用单独的CPU Torch环境，不向现有Demo/backend添加Torch依赖。在仓库根目录准备环境：

```bash
uv sync --project experiments/neural --frozen
cd experiments
neural/.venv/bin/python -m pytest -q
```

TRAIN-only资源试验必须先通过；输出目录只可新建，不能覆盖已经观察的运行。主运行要求代码与协议已提交且工作树干净：

```bash
cd experiments
neural/.venv/bin/python -m preflight.neural --output ../artifacts/preflight/history-increment-20261024-resource
timeout 2100s neural/.venv/bin/python -m preflight.incremental_run --config configs/history-increment-v1.json --output ../artifacts/preflight/history-increment-20261024-v1
neural/.venv/bin/python -m preflight.verify_incremental ../artifacts/preflight/history-increment-20261024-v1
```

配置绑定已有本地三次运行的冻结指纹，完整复核需要相应可信本地模型与数据缓存。公开到仓库的是轻量指标与审计记录，完整模型、词表、逐样本预测及原始数据仍在Git忽略目录。公开元数据只能提供内部一致性证据，不替代完整本地重算。

## 解释边界

每格3个seed来自同一数据集与共享VAL，只有描述性筛查意义。SGD开发链是增长/epoch变化，而神经开发包含增长/refresh；SGD的refresh还包含对未见更新条件的迁移。小网络从头训练，不能外推到预训练Transformer、LLM或LoRA。链内类别平衡的Risk-LR输出是诊断分数，Brier仅描述这些分数与事件的平方误差，不把它当自然事件率校准证明。AP提高也不能替代同预算检出提升。

本阶段依据固定出口决定是否还有具体线索；即使有正结果，也不自动确定最终题目、创新性或论文正式结论。没有稳定增量或事件不足时，停止自动追逐历史新算法，不在本轮新曝光目标上再搜索特征和参数。
