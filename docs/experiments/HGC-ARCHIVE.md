# HGC方案归档记录

归档时间：2026-10-24。用户明确同意停止当前HGC方案，继续检验历史信息是否能补充强margin，而非通过更换题目宣布选题已经解决。

当前覆盖式HGC保留为可复核的方法分析和失败案例。代码见[原实现](../../experiments/preflight/hgc.py)，固定参数与负结果见[第二轮](cpu-preflight-v2/README.md)和[可行性收尾](feasibility-closeout/README.md)，覆盖过早饱和的独立公式核对见[机制审计](feasibility-closeout/mechanisms/independent-formula-audit.json)。本阶段登记原文件SHA256，不改变其参数、组特征、目标或旧工件；不在已曝光结果上追加搜索。HGC不再作为优势方法候选进入下一轮竞争。

保留的数据清洗、真实训练链、强基线、完整候选池、冻结与评价框架继续复用。下一步的[历史增量检验](history-increment-v1/REGISTRATION.md)只把固定历史组风险当作一个输入，与个体历史一起检验其是否在margin之外提供价值；它不使用HGC覆盖目标，也不将Risk-LR包装成新算法。

历史报告中的“预实验收尾”指当时固定HGC可行性矩阵已经结束，不能理解为已完成新用户授权的增量检验、神经验证或论文正式实验。原研究题名和8份来源材料保留追溯；新题目与创新性仍须由具体的新证据决定。
