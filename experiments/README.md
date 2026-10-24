# CPU开发预实验

已实现独立包`preflight`，用于先验证真实数据、四版链、自然未来翻转及强基线是否可运行。两轮结果见[最新HGC报告](../docs/experiments/cpu-preflight-v2/README.md)与[首轮报告](../docs/experiments/cpu-preflight-v1/README.md)，最新经过见[开发日志](../docs/development/logs/2026-10-24-cpu-preflight-v2.md)。第二轮已有固定最小HGC；通用研究平台和正式TEST评价仍未实现。

第二轮已实际执行的入口（输出目录现已存在，重复执行会拒绝覆盖）：

```bash
cd experiments
uv run python -m preflight.round2 --output ../artifacts/preflight/cpu-pilot-20261024-v2
uv run python -m preflight.verify2 ../artifacts/preflight/cpu-pilot-20261024-v2
```

`round2.py`按新登记先训练全部模型，再在任何DEV预测前审查语义推理身份；`hgc.py`只接受全D历史与P表示；`identity.py`只给准备器/审计器使用，不传目标权重给selector。第二轮83文件/2,064单元/516条主预算成本已复核。当前两轮开发上限已用完，不继续同DEV寻优；当前HGC在检出及成本上均未达到登记筛查规则。

完整复核需本机两轮可信工件及模型（verify2会加载本运行器产生的pickle），首轮freeze哈希固定在配置中。仓库的摘要不包含词表/权重/逐样本数据；仅克隆仓库不能恢复首次工件。缺少工件时须恢复原本地备份，不能换一份新跑的旧实验冒充同一曝光历史。以下保留首轮复现说明，不意味着允许追加开发寻优。

需要Python 3.11+、uv和curl；实际执行环境/版本在报告中记录，依赖由本目录`uv.lock`锁定。该环境与Web后端分开。

```bash
cd experiments
uv sync --frozen --cache-dir ../.cache/uv
uv run python -m preflight.fetch --output ../datasets/massive-1.1
uv run python -m preflight.runner --output ../artifacts/preflight/my-new-pilot
uv run python -m preflight.verify ../artifacts/preflight/my-new-pilot
uv run pytest -q
```

每次训练必须用不存在的新输出目录，避免覆盖原登记和结果。下载器使用[MASSIVE官方项目](https://github.com/alexa/massive)发布的1.1压缩包，约40MB；核对固定SHA-256，仅解出中文文件及许可/NOTICE，不解出任意归档路径。数据和权重不提交Git。

| 文件/目录 | 职责 |
|---|---|
| `configs/cpu-preflight-v1.json` | 首轮开发登记：数据来源、清理、CPU链配方、预算、方法、种子及信号规则 |
| `preflight/fetch.py`、`data.py` | 固定来源下载；按来源/同文组件审计与排除；仅返回TRAIN和两类DEV |
| `preflight/baselines.py` | 只收自身f0/f1/f2历史、f2概率及P表示的9种选择器 |
| `preflight/runner.py` | TRAIN-only训练、模型恢复检查、全矩阵文件冻结、冻结后DEV评分与成本采集 |
| `preflight/verify.py` | 核对冻结工件、事件及完整矩阵，从已存预测重跑评分器验证报告 |
| `tests/` | 清理隔离、选择规则、评分边界及审计篡改测试 |

默认配方：MASSIVE 1.1 zh-CN，TRAIN按类别分层嵌套抽样；字符TF-IDF＋逻辑回归，冻结同一实现种子40% TRAIN拟合的表示。数据增长40/60/80/100%与正则化C=0.25/0.5/1/2两个更新家族，各3个训练种子，每链f0—f3四版。预算20/50/100/200，主预算100；Random、Stratified、PastFlip、KCenter各20个选择种子，其余5种确定性方法各1次。全部6链共2,040个选样单元，在显式调用目标DEV预测之前冻结。

正式TEST存在于中文原始文件中，仅用于最初无模型的跨分区组件审计/清理和计数；不作为训练或任何模型的输入，也不选样、预测或评价。DEV_MODEL与DEV_SELECTOR按组件hash固定划分，不允许以目标效果改变分区。当前代码没有GPU训练入口。

首轮中数据增长f3与同种子正则化f2模型相同，**不能声称全局目标行为在冻结前均未见**；该配置仅保留为开发预实验复现入口，不用于正式盲评。下一轮须另行登记、核对跨链语义模型身份，不覆盖此配置。冻结文件和事件审计记录实际路径，不构成操作系统层面的访问隔离。

完整本地工件在`artifacts/preflight/<run>/`，含模型、向量器、选择ID、预测和排除清单。仅加载本运行器自己生成的本地模型pickle进行恢复检查。Git中的轻量报告不包含原文、权重或逐样本预测，因此仅克隆仓库不能重算首轮全部单元；可以用上述命令新建开发运行。严格追溯首轮代码时使用报告记录的`08cd7ad`及依赖锁，新运行不会覆盖首轮审计。

计时目前区分训练、表示、整批基线选择和目标推理；尚无每方法、同范围、含完整预处理的成本比较。`max_training_seconds_per_model=180`在fit返回后检查，不能当成强制中断超时。计划包`regresslab_experiments.cli`、通用lab合同、Risk-LR/Behavior-Anchor/Grad-PD、外部数据和LoRA迁移仍见[实施计划](../docs/engineering/v2/07-implementation-plan.md)，尚未实现。
