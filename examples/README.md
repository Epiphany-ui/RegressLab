# 可重复生成的合成工程夹具

本目录全部文本、标签和新旧预测均由本地脚本编造，只验证导入、计数、分组、套件和重放流程。它们不是 MASSIVE 数据，不来自真实模型推理，不代表训练效果、真实退化或精选策略收益。A/B 是夹具标签，没有经过人工标注的任务语义。`raw_response` 是合成的 JSON 响应，不是外部模型运行记录。

在仓库根目录执行 `python3 scripts/make-fixtures.py` 可逐字节重建六个 JSONL 文件和 `expected-metrics.json`，不联网且只使用 Python 标准库。脚本会校验 NFKC/空白归一化后的文本全局唯一、标签词表、角色数量、预测完整覆盖、单份预测唯一 run_id 和响应标签一致性。

| 数据组 | canonical 数据集 | 旧版 / 新版预测 | TRAIN | DEV | DISCOVERY | CONFIRM | AUDIT | 每份预测行数 |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 精确计数 | [dataset.jsonl](dataset.jsonl) | [old-predictions.jsonl](old-predictions.jsonl) / [new-predictions.jsonl](new-predictions.jsonl) | 8 | 2 | 12 | 4 | 4 | 16 |
| 分组流程 | [discovery-dataset.jsonl](discovery-dataset.jsonl) | [discovery-old-predictions.jsonl](discovery-old-predictions.jsonl) / [discovery-new-predictions.jsonl](discovery-new-predictions.jsonl) | 8 | 2 | 96 | 96 | 32 | 192 |

两组均含 TRAIN 的 A/B 各四行、DEV 的 A/B 各一行。所有组件仅含一行，不跨原始分区。test 的 `group_id` 通过逐个扫描候选并计算 `SHA256('split-v1|42|'+group_id)` 前 16 个十六进制位选择，按既定 50%/25%/25% 区间确定角色；没有覆盖系统的角色划分。为便于演示，文件按所需角色取固定数量，整体数量不模拟真实抽样分布。

每份预测只覆盖 DISCOVERY + CONFIRM，完全不含 AUDIT/训练/开发行。旧、新两份使用不同且固定的 UUID；`prediction_label` 与 `raw_response` 中唯一的 `label` 一致。canonical 数据和预测均没有 `outcome` 字段，四格结果须从 gold 和两版预测实际计算。原始十二行夹具的 `fixture:01`—`fixture:12` ID 保持不变，全部落在 DISCOVERY。

## 精确计数的预期结果

`a` 为双方正确，`b` 为旧对新错，`c` 为旧错新对，`d` 为双方错误。准确率和差值均应由所选角色独立计算；D+C 合计只供测试核对，不能替代 D 发现与 C 确认的隔离。

| 范围 | n | a | b | c | d | 旧准确率 | 新准确率 | 下降 | 负向翻转率 | 正向翻转率 | 旧正确样本退化率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DISCOVERY | 12 | 6 | 3 | 1 | 2 | 3/4 | 7/12 | 1/6 | 1/4 | 1/12 | 1/3 |
| CONFIRM | 4 | 2 | 1 | 1 | 0 | 3/4 | 3/4 | 0 | 1/4 | 1/4 | 1/3 |
| D+C | 16 | 8 | 4 | 2 | 2 | 3/4 | 5/8 | 1/8 | 1/4 | 1/8 | 1/3 |

DISCOVERY 的单侧精确 McNemar 原始 p 值为 `0.3125`，与 [成对计数金标准](../docs/contracts/fixtures/paired-expected.json) 一致。十二行少于默认发现门槛 30，所以正确的默认行为是没有候选，不能降低生产阈值让夹具“显著”。CONFIRM 仅四个独立组件，也不足默认确认门槛 40。

## 分组流程的预期结果

大夹具 D 与 C 分别都是 `n=96, a=64, b=24, c=4, d=4`，旧准确率 `11/12`，新准确率 `17/24`，下降 `5/24`（20.8333 个百分点），负向翻转率 `1/4`，正向翻转率 `1/24`，旧正确样本退化率 `3/11`。

D 中 `has_negation=true` 恰有 48 行，`a=20,b=24,c=0,d=4`，下降 `1/2`，可触发默认发现阈值；它的 C 对应组也是 48 个独立组件。每个角色另有 48 行不含否定字、48 行含数字、48 行含问号；四种长度区间各 24 行。文本长短、数字和问号都由表面特征直接提取。成员重叠时不可把组内负向翻转相加当作独立错误总数。

这些模式是为了覆盖软件分支而明确设计的。大夹具的支持量不构成真实实验资格：没有真实权重、训练产物、DEV100×3新推理稳定性报告或未来版本盲测，不应把它登记为真实训练更新或正式 LLM 确认证据。Demo 可以演示固定公式；正式使用仍须执行[数据协议](../docs/specs/03-data-protocol.md)、[实验协议](../docs/specs/11-experiment-protocol.md)和[模型版本协议](../docs/specs/19-model-version-protocol.md)的来源、冻结与证据模式门禁。

[expected-metrics.json](expected-metrics.json) 包含各范围的完整小数值和未经支持量门槛/Holm校正的精确原始 p 值。这些 p 值仅用于核算公式，不是确认状态，不能直接作为产品 `confirmation.p_raw`，更不是模型有效性结论。
