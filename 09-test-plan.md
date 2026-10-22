# 测试、验收与质量保证计划

本文件规定未来实现的测试，不声称产品已通过。文档包的静态验证与独立评审另见14。

## 1. 策略与夹具

纯函数pytest → PostgreSQL集成 → FastAPI合同 → Vue组件 → Playwright端到端 → 故障恢复与性能。单元测试不访问网络、不训练大模型；集成测试用独立临时数据库和文件卷，不清空开发库。

`contracts/fixtures/paired-cases.jsonl`为12行合成金标准；`paired-expected.json`给手算四格表；`selection-fixture.json`给最大覆盖选择金标准。新增`selection-baselines.json`核对五基线与消融的手算顺序。这些仅证明工程计算，不代表MASSIVE真实模型性能。P0演示另用真实数据、Ollama/微调真实预测及CPU对照，合成夹具不补足真实更新验证。

## 2. 测试矩阵

| 测试ID | 输入与断言 | 对应需求 |
|---|---|---|
| TC-01 | 名称边界1/80/81，跨项目ID返回404 | FR-01 |
| TC-02 | UTF-8/CRLF/空行/坏JSON；错误行与总数正确、无半READY | FR-02 |
| TC-03 | 修改READY版本被拒，hash对排序/内容变化符合03 | FR-03 |
| TC-04 | 同group跨分区/跨语言、同文本异gold、transitive duplicate均被发现 | FR-04 |
| TC-05 | 预处理fit只接TRAIN；构造只在C出现词，词表不得包含该词 | FR-05 |
| TC-06 | 预测缺/重/多ID、未知label、附带gold字段全部拒绝 | FR-06 |
| TC-07 | 合法逐样本覆盖；adapter超时保留执行错误，不进入能力分母 | FR-07 |
| TC-08 | 不同dataset/scope/labelset禁止比较 | FR-08 |
| TC-09 | 12行夹具a6/b3/c1/d2、所有比率、无分母null | FR-09 |
| TC-10 | 调换C/A内容不改变D候选、排序、hash | FR-10 |
| TC-11 | max_depth2、同字段互斥、Jaccard去重与稳定tie-break | FR-10 |
| TC-12 | b20/c0时单侧p=2^-20；b0/c0时p=1；符号方向正确 | FR-11 |
| TC-13 | Holm输入[0.001,0.03,0.04]→[0.003,0.06,0.06]；含p1且m不缩水 | FR-11 |
| TC-14 | C支持39→不足，40才可检验；显著但drop<0.05不确认 | FR-11 |
| TC-15 | 同模型内容对并发confirm只有一个ConfirmationUse；原Analysis恢复不再消耗 | FR-12 |
| TC-16 | case/sample接口请求C/A返回403，返回内容无泄漏 | FR-13 |
| TC-17 | 人工DISMISSED备注不足拒绝；备注不改p/状态/计数 | FR-14 |
| TC-18 | 精选只用D旧正确；可手算覆盖顺序；预算超池、零池、截断 | FR-15 |
| TC-19 | READY套件不可改，导出重读hash一致；ID/selection_rank唯一 | FR-16 |
| TC-20 | 全对PASS、合法错FAIL、缺预测ERROR，非法标签不算普通错误；整份未覆盖预测不得用于比较 | FR-17 |
| TC-21 | JSON Schema验证、HTML转义script/onerror；不导出C/A案例 | FR-18 |
| TC-22 | worker进程中断、租约超期、旧attempt迟到发布被拒 | FR-19 |
| TC-23 | 排队取消/运行取消/重启恢复；终态与文件指纹一致 | FR-19 |
| TC-24 | 主流程各页、刷新恢复、网络中断不假失败、360px关键操作可见 | FR-20 |
| TC-25 | 401、日志脱敏、文件路径穿越/超限、审计事件 | FR-21/NFR-07 |
| TC-26 | 无API密钥，干净库完整跑通真实公开数据演示 | FR-22 |
| TC-27 | 解释响应乱JSON/虚构case_id/数字篡改/超时，分析仍可用 | FR-23 |
| TC-28 | HTTP allowlist/重定向/恶意输入/预算重试，gold不外发 | FR-24 |
| TC-29 | 单scope相同幂等key回原响应；不同body409；队列满429 | NFR-06 |
| TC-30 | m=0、所有模型相同、旧全错、无确认退化的边界 | FR-09/11/15 |
| TC-31 | 多语言同component只贡献一个确认统计单位 | FR-04/11 |
| TC-32 | 恢复备份后模型/报告/suite全部hash可验证 | NFR-08 |
| TC-33 | PRECOMPUTED导入成功只排一次judge；失败终态ERROR，新Replay使用新预测集 | FR-17/19 |
| TC-34 | 数据/模型/suite取消分别映射INVALID/FAILED/FAILED；仅Analysis允许人工resume | FR-19 |
| TC-35 | 混淆变化old/new/delta与逐例聚合一致；前50截断与全量分页可核对 | FR-09 |
| TC-36 | 分层截断配额精确、标签全保留、组义务不被悄悄删除 | FR-15 |
| TC-37 | 五基线无放回、size精确；stratified最大余数配额，B小于类别数合法；共享截断池 | FR-15/NFR-02/M11 |
| TC-38 | 整数gain下数学优先级成立；实际直接比较(gain,H,D)，极小D差异不因大系数浮点舍入丢失；已覆盖收益归零、ID同分 | FR-15/NFR-01 |
| TC-39 | ablate_history修改H不改选择；ablate_diversity修改向量不改选择；完整方法仍可受影响 | M11 |
| TC-40 | diversity首条由seed确定，零向量规则一致、距离逐轮更新；20个seed全部保留 | M11/NFR-02 |
| TC-41 | 开发未来目标与正式未来目标hash交集非空时拒绝正式注册；正式C/A不能用于开发 | M11 |
| TC-42 | 冻结后修改方法/权重/预算/seed/模型hash被拒；复制dataset ID不重置C使用权 | M11/FR-12 |
| TC-43 | NA不算晋级成功；先按seed再按链聚合；开发门槛及参考基线不由正式结果改写 | M11 |
| TC-44 | 算法change log含旧新hash/唯一改动/证据/决定；新版本不覆盖旧suite与报告 | FR-16/NFR-08/M11 |
| TC-45 | TRAIN-only监督目标mask、EOS、padding与全序列长度；被测输入无gold，完整60标签不截断 | FR-26 |
| TC-46 | v1/v2/v3来自相同run、预定steps，adapter权重变化，父版本正确；同run只计一链 | FR-26/27 |
| TC-47 | 32步烟测与保存恢复，非NaN、实际显存/耗时记录，超预算不写虚假通过 | FR-26 |
| TC-48 | OLLAMA只用服务端固定endpoint和已安装tag，前后digest不一致拒绝发布 | FR-28 |
| TC-49 | raw_response与run_manifest持久化；run_id混用、scope/权重/推理hash错拒绝；C/A原始响应UI不可读 | FR-06/27 |
| TC-50 | DEV固定100例×3，缺/重ID、不同标签、不同runtime、错误source或不足100拒绝确认资格 | FR-27 |
| TC-51 | DESCRIPTIVE_ONLY不读C且不占ConfirmationUse，report明确模式；不能点击确认绕过 | FR-11/27 |
| TC-52 | 外部manifest校验只证明内部一致，provenance_status仍DECLARED，不冒称真实训练核验 | FR-27 |
| TC-53 | v3预测先于套件冻结、污染formal或复用已读C/A时拒绝主注册/明确探索，不重命名洗白 | M11/FR-27 |
| TC-54 | 同权重改prompt不满足TRAINING_UPDATE；不同后端/量化只作单独变化类型 | FR-27 |
| TC-55 | LLM中断重试完整新run，失败raw工件留存；禁止拼接不同run的成功行 | FR-07/19 |
| TC-56 | 无确认分组、A观察组分母0、无自然翻转时正确回退/NA，不能报100%覆盖 | FR-15/M11 |
| TC-57 | 未来v1→v3与相邻v2→v3基准池分别定义；训练链/selector种子/样本数不混作独立重复 | M11 |
| TC-58 | Windows容器到宿主机Ollama地址、限时连接、停服/CPU分担/显存不足均有可操作错误 | FR-28/NFR-09 |
| TC-59 | 复制dataset UUID或只改来源元数据不重置evaluation_data_sha256确认预算，并发重复仍仅一次 | FR-12/27 |
| TC-60 | 原始冲突默认停止；显式清洗删除整个跨分区/冲突组件、留排除清单/哈希、保留标签；不能按模型效果清洗 | FR-02/04/26 |
| TC-61 | Lab审计/全池只在全部suite冻结后导出，独立manifest不能进入HTTP；A标签只最终一次读取，未来单run完整 | M03T/M11/FR-27 |
| TC-62 | raw_response非空，按冻结parser_version重解析所得标签与prediction_label相同；额外JSON键/非法标签/不一致拒绝 | FR-06/07/27 |

## 3. 统计测试的额外要求

- 精确p值对SciPy，Holm对statsmodels，指标对sklearn对照，不仅测试自己复刻的公式。
- 负向与正向翻转对调时检验方向必须相反；不能误用双侧p当单侧。
- 计数守恒a+b+c+d=n；每一比率分母正确；四格表与样本列表distinct数一致。
- bootstrap固定种子输出可重复；仅描述性不作为gate；n=1/常数z正确处理。
- 工程正确性使用预构造极端分布；论文效果使用不参与调参的真实数据。不能用合成注入结果证明真实退化覆盖率。

## 4. 性能与恢复测试

性能环境记录CPU型号、可用内存、系统、容器限制、锁文件hash。使用10,000行库和单CPU作业，预热后测100次分页GET，p95目标≤1秒。导入50,000行、500项suite、最坏两原子枚举记录峰值RSS与时长，不预造达标结果。

恢复：在每个任务的输入验证后/中间批次/文件发布前/DB提交前终止worker；确认没有两个最终产物、没有无文件成功状态。旧worker恢复后attempt fence拒绝写入。测试的时间等待可用可控clock替代90秒真实睡眠。

## 5. 最终验收场景

AT-01：操作者在干净环境启动服务，创建项目、导入真实数据并查看manifest。

AT-02：按19用TRAIN-only LoRA产生真实v1/v2及预留v3，保留权重/adapter/日志，在同一推理后端完成v1/v2真实预测并导入；同时完成LR重新训练对照与Ollama连接/真实推理。若自然无退化，正确显示无候选；另用合成夹具证明分组和确认状态。

AT-03：合格稳定性证据下CONFIRMATORY确认一次，再次不消费新证据；无/失败稳定性报告时DESCRIPTIVE_ONLY完成D、C为null、confirm409。不得用合成稳定性证明替代真实模型。

AT-04：生成50项或实际可用大小套件，先冻结所有方法的hash和时间，再生成/解封v3预测，实际重放并核对PASS/FAIL/ERROR；来源不是旧缓存。

AT-05：数据、权重、依赖准备后断网，无API密钥仍可完成主流程；服务恢复不混合不同LLM推理run。离线准备失败须记录，不能伪造已完成。

AT-06：按用户手册重新部署并恢复备份，报告含来源、版本、局限而没有“安全认证”误导文案。

验收记录填写实际时间、环境、操作者、git_sha、失败项与修复提交；不允许只写“测试通过”。

## 6. 文档与实证验收的区别

静态合同与手算夹具通过不表示TC-45—58、真实微调、GPU资源或应用端到端已经通过。若训练失败或未完成真实语言模型链，必须列为未满足，不能用LR或合成输出冒称已完成主实验。研究无增益与工程未实现是不同状态。
