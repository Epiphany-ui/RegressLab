# 模型版本生成与真实更新验证协议

版本1.3 · 2026年10月22日。本文定义未来实现的实验准备流程，尚未下载、训练或测量。与03的机器身份合同、11/17的实验协议共同使用，不提供伪造的权重hash或训练日志。

## 1 为什么必须有版本生成流程

主问题是修改后是否出现退化。主实验使用同一基础小语言模型在公开训练集上的继续训练；不以两个不相干模型的横向分数代替修改前后验证。LoRA是已有训练工具，不是本项目提出的优化算法。[官方方法说明](https://huggingface.co/docs/peft/v0.21.0/package_reference/lora)

## 1.1 原始数据冲突的预处理

原始语料是否有跨官方分区的归一化重复或冲突尚未实测。默认先审计，存在冲突则停止，不把整个原始集已可用当事实。若采用03的`--exclude-cross-partition-components`清洗配置，须在任何模型结果之前冻结，删除整个跨分区/冲突连通组件的全部行，记录全部排除ID/理由/计数/hash，核对保留60类，不移动官方分区。结果注明“清洗后的MASSIVE子集”，不能冒充完整官方benchmark成绩；规范导入器对残余冲突仍拒绝。

评测身份使用evaluation_data_sha256，排除来源名称/URL/许可等外部元数据，复制dataset UUID或改来源描述不能获得新的C确认使用权。不得重命名或改分区来把已读过的测试证据冒充独立新数据。

## 2 主实验的来源和版本链

基础模型候选为[Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B)，记录实际下载revision、许可、tokenizer/模板和所有文件SHA256。1.7B仅在资源试验通过后作为补充，不能预先承诺在6GB上完成训练。模型公开权重与本地Ollama标签是不同来源标识，不用名字替代字节身份。

```text
固定公开权重 M0
  └─ 只在TRAIN上标准LoRA继续训练，同一训练run
       ├─ optimizer step 100 保存 v1  基准版
       ├─ optimizer step 200 保存 v2  历史候选版
       └─ optimizer step 300 保存 v3  预留后续版

v1与v2历史预测 → D发现、合格时C确认 → 所有方法套件冻结
                                               ↓
                                  才生成或解封v3评测预测
```

100/200/300是**设计者给出的起始训练预算**，不是已验证的最优步数、数据量或效果。先在TRAIN/DEV预实验；不足以学会任务、资源不可承受或出现截断时，修改配方并生成新profile版本，记录原因，在读取正式D/C/A结果或v3预测之前冻结。不得看过正式效果后选择更有利的训练轮次。

v1可声明无项目内父模型、其基础revision在来源中记录；v2的父版本为v1，v3为v2。三者记录同一个chain_id、不同step和真实权重清单。有效权重身份包含基础权重与adapter，不能只给相同base模型hash而忽略LoRA。三个检查点只算一条相关版本链；selector随机种子也不能增加独立训练次数。

## 3 可执行的默认训练配方

实验环境单独创建`experiments/`，开发时生成真实锁文件，不向Web后端强行加入CUDA依赖。先用普通LoRA；QLoRA仅作开发阶段资源替代方案，须固定新profile，所有比较版本使用相同量化，不能一边换量化一边把差异全归因于训练。

| 项 | 起始值和规则 |
|---|---|
| 数据 | MASSIVE1.1 zh-CN，仅TRAIN；原始DEV调配置；TEST不进入训练/调参 |
| 输入 | 固定任务说明、完整标签ID/说明表和原文本，采用固定tokenizer聊天模板，关闭思考模式 |
| 目标 | assistant输出`{"label":"固定标签ID"}`；gold只在监督目标，不进入被测用户输入 |
| 损失 | 仅assistant目标token参与监督；prompt和padding置ignore_index；检查模板边界，禁止全序列误监督 |
| LoRA | r=8，alpha=16，dropout=0.05，target_modules=[q_proj,v_proj]，task_type=CAUSAL_LM |
| 优化 | AdamW，learning_rate=0.0001，weight_decay=0，constant调度，seed=42，batch_size=1，gradient_accumulation_steps=8 |
| 保存 | optimizer steps100/200/300；完整保存adapter、base引用、optimizer/scheduler/RNG状态及日志 |
| 序列 | 初始max_seq_length=1024；完整序列含所有标签、模板、原文、目标和EOS，禁止静默截断 |
| 精度 | 先测试fp16；如选择bf16须先确认支持并另行冻结，所有比较保持一致；不预填实测支持 |
| 显存控制 | gradient_checkpointing开启，训练use_cache=false，单训练进程；不与Ollama驻留争抢显存 |

先对完整TRAIN/DEV序列做token长度扫描。任一训练或评测输入超限时停止该profile，按开发记录提高长度并重测显存，或换事先说明的任务方案，不能删掉标签、悄悄切文本或只排除不利的正式样本。最终语料和输入长度检查清单必须完整保留。

固定采样器只打乱TRAIN，训练流不由测试结果反馈。每个optimizer step实际样本数、累积计数、样本ID序列摘要和有效目标token数写入日志。中断恢复只有在profile、数据、base、环境和完整状态匹配时续训；否则建立新run，不能把两次不同训练拼成一条。

## 4 资源和分类预实验

先做32个optimizer steps的短程训练，检查loss非NaN、目标mask正确、adapter确实变化、保存/恢复正常，记录峰值allocated/reserved显存、RAM和墙钟。32步不是完整分类效果实验，也不假称能提供目标精度。根据稳定阶段耗时估计300步总成本，正式单链暂定12 GPU小时护栏；估计超出时只在开发阶段缩预算或改配置并重新冻结。计时包括验证、保存和推理，不隐藏初次准备。

先对历史v1/v2用开发阶段固定300—500条DEV分类，报告合法率、准确率、macro-F1、双向翻转和分组支持量，预实验不保证足够统计功效。负向翻转极少时暂停相应效果主张，按11预登记有限替代，不能人工造错。没有自然退化本身是结果。

稳定性记录固定为按03规则取得的100条DEV，历史v1/v2每版3次独立完整推理run，保留run_id、ID、标签、原始响应及环境；不足100例时本主方案不满足确认性门槛，只作描述或在正式读取前重新设计。每次重启/清缓存后的策略须一致登记。100%合法且同版3次标签完全相同才通过观察门槛，不能把重复行当新增独立样本。即使通过，也只说明这批开发样本未观测到波动。

历史v1/v2不通过时可在正式注册前于DEV尝试确定性设置或CPU推理；仍不通过则DESCRIPTIVE_ONLY，禁止把运行噪声写为独立确认的权重退化。正式运行发现噪声或环境变化也应停止原确认性主张，记录并降级，不靠多数投票临时改变规则。

v3的DEV稳定性推理也必须等全部selector套件冻结后再做，不仅禁止提前查看其正式D/A预测。不得依据v3结果改提示词、解码、后端、训练或选择；失败时保留失败并将未来权重效果主张降级/停止，不能挑另一候选顶替。历史v1/v2已符合条件的RQ1不因此伪造为失败，未来RQ2单独报告限制。

## 5 推理和导入合同

主检查点采用同一Transformers/PEFT推理环境、精度、tokenizer、提示词、类别表和解析器。使用eval/inference_mode，关闭训练dropout，do_sample=false；如普通生成不能保证合法标签，可在DEV预先实现标签JSON序列的token前缀约束，允许集合只能来自固定label_vocab，绝不可读取gold。约束树、最大输出长度、EOS处理及parser_version=label-json-v1须加入推理配置hash；CPU使用label-literal-v1，服务器核对原始响应与声明标签一致。该设置不保证标签正确。

v1/v2/v3的推理配置指纹必须相同，权重指纹不同，change_type=TRAINING_UPDATE。模型来源真实性对外部导入仍为DECLARED；服务器只能校验提供记录的一致性，不证明外部训练从未作弊。权重文件、adapter、训练日志及原始预测保留本地归档，Web不上传执行模型。

先在系统创建PRECOMPUTED模型及PredictionSet，取得服务器run_id、scope_hash和冻结ID清单；导出仅含sample_id/text的推理输入。外部脚本生成带run_id、prediction_label、raw_response的JSONL及run_manifest，再导入；字段以[03](03-data-protocol.md)与[OpenAPI](contracts/openapi.json)为准。不能先随便生成一个run_id，再绕过scope核对。

两份完整合法预测才允许分析，错误和覆盖率单独保留。不得把非法标签替换成gold、删掉失败行、选多次推理中最好的一次，或把旧缓存当新调用。LLM失败恢复的整run/attempt策略按02/03；不从不同随机实现拼接一份“成功”预测。

## 6 逻辑回归对照怎样修改

保持字符TF-IDF(2,4)、C=1、seed=42和其余03默认参数，按分层稳定hash产生嵌套TRAIN子集，比例0.5→0.8→1.0，重新拟合完整Pipeline得到lr_v1/lr_v2/lr_v3。每类按SHA256(UTF8("lr-train-v1|42|"+sample_id))升序、sample_id UTF-8字节序同分排列；q_l(f)=max(1,floor(f*n_l))，f=1时q_l=n_l，取前q_l。总数不保证精确等于总量乘比例，记录每版IDs/hash；该规则保证嵌套。不得利用DEV/TEST决定某条训练数据是否进入。

该过程属于增加训练数据后的真实模型更新，特征词表与权重都可能变化；不把它称为仅修改单个系数的因果实验。逻辑回归也可调正则化，但本对照先固定C以减少因素；如开展C调整，另列预注册链。[官方参数](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)

## 7 横向模型和API的边界

Ollama公开模型可真实运行作工程验收或模型替换比较，但0.6B、1.7B、4B不是同一权重的继续训练版本。普通API只改提示词/示例时标APP_CONFIG_UPDATE；更换服务标MODEL_REPLACEMENT，不冒称自行微调。API不等于闭源，未知参数量按未知记录；费用按运行当天官方价和实际用量核算。

微调模型转换到Ollama属于可选实验；官方有Safetensors/GGUF导入说明，不代表本模型、本adapter、当前版本均兼容。未通过转换时，按上述外部同后端推理/导入闭环即可，不用更换后端制造假权重差异。[导入说明](https://docs.ollama.com/import)

## 8 产物、冻结顺序和失败出口

每条链保存registration.json、training-profile.json、来源及许可、base与adapter文件清单、TRAIN IDs/哈希、标签/模板/tokenizer、训练状态与日志、环境锁、checkpoint step/parent、推理稳定性记录、预测run_manifest、JSONL、原始响应及成本。不能预先编造真实hash；缺失时明确未满足。

顺序为开发配方与数据冻结→真实训练与版本登记→历史v1/v2推理→D家族冻结→满足资格的一次C→全部selector套件hash与冻结时间写入注册→v3预测生成/解封→A最终描述审计。v3权重可提前保存，但评价预测不得提前暴露给选择程序或研究者用于调整。

正式方案至少包含一条真实语言模型更新链和一条LR对照链，结论按链分别报告，不能混成大样本。若微调在现有资源上失败或版本无有效分类能力，先修复/缩配方并重新预实验；仍失败须报告主实验未满足，与导师调整实验范围，不能静默用传统模型代替后仍声称验证了语言模型微调。若方法无增益，保留系统和负结果。


## Lab最终审计与全池预测入口

产品HTTP预测scope继续只允许D+C/SUITE，不开放AUDIT。完整研究评价由11§7.1的受审计lab命令处理：

```text
python -m regresslab.cli lab prediction-inputs --registration <registration.json> --target-model <model-version-id> --scope AUDIT|POOL --output <inputs.jsonl>
python -m regresslab_experiments.cli infer --manifest-kind lab --model-manifest <model.json> --run-manifest <lab-run-manifest.json> --inputs <inputs.jsonl> --output <predictions.jsonl>
python -m regresslab.cli lab prediction-validate --manifest <lab-run-manifest.json> --predictions <predictions.jsonl>
python -m regresslab.cli lab evaluate --registration <registration.json> --predictions <validated-lab-run-directory> --output <result-directory>
```

M11实现上述输入导出、预置LabPredictionRunManifest和最终评价；M03T的同一离线infer模块新增--manifest-kind product|lab（默认product），两个manifest严格判别。lab manifest见contracts/lab-prediction-run.schema.json，含registration/evaluation/权重/推理/全部suite冻结hash及ID集合，不能导入产品HTTP。导出时同时生成PREPARED manifest，预登记模型白名单仅允许固定v1/v3。A和完整共同P'的未来预测均在套件冻结后；A逐例gold仅最终evaluate读取一次。失败或hash不符不出正式结果，不能把任意本地ID列表伪装成A。研究全池/A推理成本完整计入，不把查缓存当节省模型调用。

新增测试TC-61：未冻结全体suite或模型不在登记中时拒绝lab AUDIT/POOL输入导出；输入无gold、预测完整且单run、LAB_ONLY在HTTP导入被拒、最终A标签读取一次，错误时不发布正式评价。测试模块为tests/unit/test_lab_prediction_boundary.py与experiments/tests/test_lab_manifest.py，先红后实现，CLI入口字段与Schema一致。
