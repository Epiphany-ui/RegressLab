# v2 规划与迁移检查记录

2026-10-23。本次范围是研究方案导入、架构与软件开发规划、文档组织及旧Demo兼容维护；不是HGC实现或研究效果验收。

来源和差异见[导入清单](../research/v2/import-manifest.json)。任务开始时本地基线为`46f4ed4`；同步检查实际取得远端`a702894`及其README/设计文案修改，通过正常Git历史集成保留，不强制覆盖远端。源包提到的`a702894`因此可确认是实际远端提交，但其来源测试陈述仍与本轮测试分别记录。

## 本轮实际交付

- 8份研究源Markdown逐字节导入，含原始算法、实验、定位和文献清单。
- 7份工程正文，涵盖范围/决策、模块架构、领域及文件/SQLite合同、工作流/访问/成本、Demo迁移、验收和P0—P7开发计划。
- `research-v2-draft1` JSON Schema草案：11类顶层工件、45个命名定义，另有合同使用说明；它不是已经运行的lab协议。
- v1.3规格/合同/验证和旧产品路线归档；根README/文档导航/当前实现状态转向v2。现有Demo只调整测试和生成器的历史合同路径，不改变API、算法、UI或数据库内容。
- `lab/`、`experiments/`只建立职责README，不伪造算法源码、训练包或锁文件。

## 实际检查结果

| 检查 | 实际结果 | 范围 |
|---|---|---|
| `backend/.venv/bin/python scripts/check-docs.py` | 8组PASS；1项已知来源附件警告 | 8源摘要、全部本地文档目标、JSON/文内引用、2020-12 metaschema及合成形状边界 |
| Schema合成形状见证 | 11类顶层shape均可校验；目标字段/访问层/主增强分支/冻结身份/消融与成本负例通过 | 所有见证在内存中构造，明确synthetic；不验证真实工件语义或产生科研结果 |
| `node scripts/check-legacy-design.cjs` | 17/17 PASS | 归档v1.3静态合同；不包含v2科研效果 |
| `cd backend && .venv/bin/python -m pytest -q` | 67 passed，约1秒 | 原领域35＋API32项兼容回归，包含临时SQLite、导入与导出 |
| `python3 scripts/make-fixtures.py`及与Git基线逐字节对比 | 7个生成工件一致 | 基础/分组JSONL及expected-metrics；没有改旧Demo数据协议 |
| `backend/.venv/bin/python -m regresslab.cli doctor` | SQLite ok、历史摘要核验通过、前端已构建 | 现有本地Demo；不是研究数据库验收 |
| 本地服务 `/api/demo/health` 与 `/` | HTTP 200；Demo版本0.1.0 | 实际启动原脚本后的接口/静态页烟测 |
| `git diff --check` | PASS | 文档与路径变更无空白错误 |

后端测试有一项Starlette关于httpx TestClient未来弃用的提示，不影响上述通过结果。没有修改前端或E2E实现，因此本轮没有重新运行浏览器6项测试或重新构建UI；那些结果仍属于[原Demo历史验收](VALIDATION.md)，不冒充v2能力。

文档检查只核对Schema形状、来源完整性和路径，不能证明代码未偷读目标、真实hash正确、概率归一化、矩阵语义完整、时间/成本真实或方法优越；这些是06/07中未来实现和研究验收的工作。

## 交叉审查中修正的问题

1. 主历史方法和完整f3增强方法的时序不可混为一个门禁。工程D15明确CORE_PRE_TARGET与引用父冻结hash的ENHANCED_TARGET_ACCESS分支；白盒/探测能力另行记录，不把它们与未声明泄漏混同。
2. Stratified的逐预算最大余数配额不保证前缀。前缀断言仅用于HGC/Facility及登记为固定序列的方法。
3. Grad-PD需要同参数坐标、类别/词表/IDF基础；D06将共同TRAIN基底设为待冻结草案，不能直接相减不对齐的CPU系数。
4. Risk-LR逐转移输入只用H_<t/E_<t，不能把当次翻转标签写进“历史次数”。
5. 工件引用区分file_sha256与语义content_sha256；费用区分研究金标准、增强方法访问、未知/估计/实测，避免复用缓存被写成免费目标推理。

## 已知缺失和未执行

源包README引用`研究方向调整方案简述.docx`，但提供目录仅有8份Markdown。检查器仅对此精确来源链接发出`SOURCE_ATTACHMENT_NOT_SUPPLIED`警告；没有放宽其他断链检查，未生成/声称审查缺失Word。可用的教师摘要是[05-teacher-brief.md](../research/v2/source/05-teacher-brief.md)。源文档未因修链接被改写。

未实现或执行：v2数据下载/清理、四版CPU真实更新、LoRA资源试验、HGC及基线、论文包复现、信息访问隔离运行器、完整冻结/解封评测、真实成本/统计结论和研究结果界面。科学参数仍有待冻结决策，清单见[01](../engineering/v2/01-scope-and-decisions.md)；下一轮按[07](../engineering/v2/07-implementation-plan.md)从lab合同、时间/池/风险及访问边界骨架开始。
