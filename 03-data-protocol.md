# 数据、金标准与版本协议

## 1. 第一版数据

主示例：MASSIVE 1.1 zh-CN，标签为意图类别。可选en-US另建版本。官方JSONL带id、locale、partition、scenario、intent、utt等字段，id关联原始平行语句。数据许可与代码许可分别保存。[S02][S03]

截至2026-10-22，数据卡写每语言19,521条，但分区表11,514+2,033+2,974=16,521；不能依描述硬编码总量或伪造缺失行。导入器以实际partition和逐行统计为准，将差异写manifest。数据卡当前报告旧式datasets加载脚本不再支持；**开发使用官方仓库给出的原始压缩包与JSONL，不依赖执行远程dataset脚本。**

默认转换先输出无模型结果参与的重复/冲突审计：按第3节同group/同归一化text连通组件，列全部跨官方分区组件、冲突gold组件、各分区影响计数；发现问题默认停止，不静默移除。可在任何正式模型结果之前预先选择`--exclude-cross-partition-components`清理profile：剔除跨官方分区或冲突gold的**整个**连通组件（TRAIN/DEV/TEST相关行全部剔除），输出exclusion_manifest（sample_id、component_key、原partition、原因、逐分区/label计数、排序ID hash、配置hash）。禁止只删测试行、搬分区或看结果后过滤；清理后canonical严格校验不变，并确认TRAIN保留全部60意图，否则停止主数据profile。名称标“cleaned MASSIVE subset”，记录原始行数和损失，不能与未清理全量结果混称。尚未实下载，不能断言必须清理或损失多少。

官方仓库：<https://github.com/alexa/massive>，“Accessing and Processing the Data”的1.1链接为获取入口。转换器接收已下载并解压的文件路径；P0不自动执行下载文件，不把下载成败隐藏在业务导入中。

## 2. canonical JSONL

一行一个对象；UTF-8，无BOM，LF。解析可接受CRLF并归一化。必须字段：

| 字段 | 类型 | 规则 |
|---|---|---|
| sample_id | string | 1—160字符，版本内唯一；MASSIVE为`locale:id` |
| group_id | string | 1—160字符；MASSIVE为`massive:id`，不含locale |
| source_partition | enum | train/dev/test，保留原始含义 |
| text | string | 1—8192 Unicode码点；原始展示值，不剥除否定词 |
| gold_label | string | 1—100字符，精确标签；MASSIVE映射intent |
| locale | string | 2—16字符，MASSIVE如zh-CN |
| metadata | object | 可选，仅允许scenario字符串；不把worker个人信息导入 |

```json
{"sample_id":"zh-CN:0","group_id":"massive:0","source_partition":"test","text":"请设置明天早上七点的闹钟","gold_label":"alarm_set","locale":"zh-CN","metadata":{"scenario":"alarm"}}
```

以上句子为格式示例，不声称复制了真实数据。没有gold的竞争评测集不能用于本项目正确率验证。样本标签错争议可标注备注，但修订gold必须生成新数据版本并说明来源。

## 3. 归一化、去重与划分

`normalize_text(s)`：Unicode NFKC；所有连续Unicode空白折叠为单空格；首尾去空白；保留大小写、标点、数字和原意。`text_sha256`对归一化UTF-8字节计算。分类器的lowercase是独立可版本化训练设置，不改变样本身份。

导入全部文件后构建无向关联：相同group_id或相同text_sha256的行连为一组（union-find）。一个连通分量若跨原始train/dev/test，拒绝版本，返回SPLIT_LEAKAGE；同归一化文本不同gold，拒绝并返回CONFLICTING_GOLD。同文本同gold可保留行，但必须同组件/同role，不算独立重复证据。

稳定`component_key`取分量中按UTF-8字节排序最小group_id。划分：train→TRAIN；dev→DEV；test分量用`u=int(SHA256('split-v1|42|'+component_key)[0:16],16)/2^64`，u<0.50→DISCOVERY，u<0.75→CONFIRM，其余→AUDIT。不按行重新随机，不使用进程内hash()。同组件内所有语言同role。分区计数以导入结果为准，不强求恰好50/25/25。

统计独立单位采用component_key。P0主示例单语言；多语言合并时同component每个slice只保留按sample_id排序首行用于**确认统计**，其余仅描述性计数。报告同时标row_support与independent_support；确认阈值使用后者。D搜索可按行，但不得把多译文行数当独立确认量。

## 4. 特征目录v1（只用可计算输入特征）

| 特征 | 定义/取值 |
|---|---|
| locale | 规范输入locale，低频值不合并以保持可解释 |
| length_bin | normalize_text后的码点数：1—8、9—20、21—40、41及以上 |
| has_negation | zh文本含任一不/没/别/无/未；en使用忽略大小写单词边界no/not/never/without/cannot/can't/don't |
| has_digit | Python正则`\d`命中Unicode数字 |
| has_question_mark | 包含`?`或`？` |

这些是表面特征，不是人工能力标签，不将“含不”解释为必然涉及逻辑否定。P0不开放任意Python表达式、SQL条件或LLM自造过滤器。metadata.scenario、gold_label、预测标签、预测正误不进入默认特征目录；类别混淆另作为描述性结果显示。

## 5. 标签与版本指纹

label_vocab：所有TRAIN gold去重，按UTF-8字节排序，2—200类；DEV/test出现未在TRAIN的gold时导入失败UNSEEN_LABEL。标签显示别名另表/JSON保存，不改变模型合同。

canonical JSON使用UTF-8、对象键排序、无多余空白、禁止NaN/Infinity。记录：raw_sha256、canonical_rows_sha256、labelset_sha256、split_manifest_sha256、feature_catalog_sha256。行按sample_id排序后分别hash；DatasetVersion.content_sha256是上述指纹与source/version/license_url的canonical JSON摘要。

另计算evaluation_data_sha256=SHA256(canonical JSON of {canonical_rows_sha256,labelset_sha256,split_manifest_sha256})；它排除source/name/version/license和UUID，作为确认复用边界，不因重新上传重置。DatasetVersion.content_sha256仍包含来源信息以追溯。

封存manifest至少包含上述hash、源URL/版本、许可文本hash、转换器git_sha、行数/独立组件数/各role计数、标签计数、空文本/冲突检查结果、实际获取时间、文档数量差异说明。未知真实下载SHA在实现时填入，禁止预先编造。

## 6. 模型、预测与scope（1.3）

### 6.1 来源与真实更新链

主实验使用公开Qwen/Qwen3-0.6B的固定revision，按19离线Transformers/PEFT在TRAIN上训练LoRA，保存同次训练step100/200/300三个checkpoint为v1/v2/v3；32步烟测先检查6GB显存可行性。权重、tokenizer、依赖锁和训练日志实际生成后填hash，不能预先编造。输入只含text与统一标签说明，不能带该样本gold；监督target仅在TRAIN训练过程使用gold。推理限制到合法标签前缀树，所有版本相同后端/精度/提示词/解码，不经Ollama转换再冒充单一权重变化。v3的DEV稳定性及正式D/A预测都须在全部selector套件冻结后才生成/解封，不允许根据v3调参。1.7B仅在实测余量后选做，不保证6GB可训练。

BUILTIN_TFIDF为CPU对照。只用TRAIN拟合，默认字符ngram(2,4)、min_df=2、max_features=30,000、sublinear_tf=true、LogisticRegression(C=1,max_iter=1000,solver='lbfgs',random_state=42)。主对照链C=1、固定特征设置，TRAIN分层嵌套子集fraction=0.5/0.8/1.0、seed42；每类按SHA256(UTF8("lr-train-v1|42|"+sample_id))升序再按sample_id UTF-8字节序，取q_l(f)=max(1,floor(f*n_l))，f=1取n_l，实际总量允许偏离名义比例。重新训练得到三个真实权重版本，但不当作三次独立训练重复。开发候选仍允许C∈{0.25,0.5,1,2}和ngram∈{(1,3),(2,4)}，只能看DEV并冻结后使用，不能拿D/C/A挑最好结果。[S10]

OLLAMA为已安装、服务端白名单内公共模型的本地推理适配。主训练链的canonical推理由离线Transformers脚本生成，再以PRECOMPUTED接入。LoRA合并/转换Ollama只是兼容实验，非P0必需，不假定Qwen3适配器导入已支持。普通API为选做外部场景，提示词改动叫APP_CONFIG_UPDATE，不叫自身权重更新。

### 6.2 不可变身份与谱系

所有hash采用第5节canonical JSON。精确字段与JSON形状见model-provenance.schema.json：

| 字段 | 唯一含义 |
|---|---|
| weights_sha256 | 按name排序的权重文件manifest摘要；同时包含base和adapter，文件条目有name/sha256/size_bytes/role；Ollama由服务端检查的blob digest构造manifest |
| inference_config_sha256 | InferenceIdentity摘要：backend/backend_version、tokenizer_revision、prompt_sha256、label_contract_sha256、precision、decoding、runtime_environment_sha256 |
| content_sha256 | 应用版本摘要：labelset_sha256、weights_sha256、inference_config_sha256；不是单独权重hash。kind、名称、provenance和run_id不进入该身份，换登记方式不能重置确认预算 |
| provenance_sha256 | 完整ModelProvenance摘要，含实际来源revision、权重清单、训练记录和日志 |
| change_type / parent_model_version_id | TRAINING_UPDATE、MODEL_REPLACEMENT、APP_CONFIG_UPDATE、DEPLOYMENT_CHANGE或REFERENCE；父ID必须同项目、无环 |
| provenance_status / identity_verified | SERVER_VERIFIED只表示服务端亲自生成或检查其持有产物；PRECOMPUTED永远DECLARED/false，不因64位字符串或日志一致而升级为权重核验 |

CPU的weights_sha256覆盖完整已拟合Pipeline：TF-IDF词表/IDF与分类器系数都是训练产物。inference_config_sha256只覆盖固定的输入归一化、算法设置、标签合同和运行环境，不含已拟合词表/IDF，也不含训练数据fraction；fraction放training_config与TRAIN子集manifest。否则重新训练词表会被误判成推理配置变化。CPU的InferenceIdentity使用CLASSIFIER_ARGMAX、固定char特征合同作为tokenizer_revision、固定输入合同摘要作为prompt_sha256，不表示CPU实际调用文本提示词。

PRECOMPUTED注册JSON嵌入provenance对象，含有界training_log_text（≤1MiB），服务器可重算日志与manifest摘要；外部权重文件不上传，仍是用户声明。TRAINING_UPDATE的父版本先注册；父metadata必须能提供相同base revision、权重manifest和训练链。不得以v1/v2名称代替真实谱系。主训练链训练子集不变、step递增；CPU数据量链同分层规则、集合嵌套。InferenceIdentity的prompt/标签合同随版本保存，服务端仅接受与任务labelset一致的合同。

### 6.3 单次运行和完整覆盖

预测行（所有实际导入行含run_id与原始响应）：

```json
{"sample_id":"zh-CN:0","prediction_label":"alarm_set","run_id":"00000000-0000-4000-8000-000000000010","raw_response":"{\"label\":\"alarm_set\"}"}
```

可选latency_ms非负；不接收gold字段。raw_response≤32768字符，原文受限存储，不直接进普通列表。BUILTIN原始值可为所预测label；LLM保留实际原始响应，而非事后用合法标签重新拼造。server验证label属于label_vocab；JSON合法不代表标签正确。畸形/未知标签/超时计执行失败，与分类错误分开。

PredictionSet创建时分配run_id和冻结inference_config_sha256。PRECOMPUTED上传旁路model_version_id/dataset_version_id/scope_hash与run_manifest（multipart JSON字段，见prediction-run-manifest.schema.json）；manifest包含模型应用/权重/推理hash、dataset内容hash、scope、时间、环境和FRESH_INFERENCE或CACHED_PLAYBACK。全部行run_id必须匹配，时间顺序合理。外部声明不能证明确未拼接，报告保留来源限制。API_SERVICE未公开weights时weights_sha256=null、weights_manifest=[]、source_revision明确UNKNOWN_PROVIDER_REVISION，不能编造hash或标TRAINING_UPDATE；provider/model/已返回版本进入InferenceIdentity.backend/backend_version。LOCAL_CHECKPOINT/PUBLIC_WEIGHTS必须有非空权重清单与实际weights摘要。

预期ID与实际ID严格一一对应；缺失/重复/额外ID/非法标签/原始响应缺失均整体FAILED。只有两份SUCCEEDED且100%合法覆盖的预测可普通分析或重放判定。coverage分别记录expected_count、legal_count、missing_count、invalid_count、failed_count，分母为0时ratio=null；无效/失败行不进入正确率或McNemar，也不以missing-as-wrong掩盖失败。保留失败raw产物与错误摘要供排查。

scope只有ROLES或SUITE；示例`{"kind":"ROLES","roles":["DISCOVERY","CONFIRM"]}`或`{"kind":"SUITE","suite_version_id":"UUID"}`。roles固定排序；scope_hash含dataset内容hash，suite额外含suite内容hash。原sample_id不改名。零长度scope不得创建推理任务；分析D必须非空。C空时允许CPU描述/探索，确认支持0、全局C指标null、INCONCLUSIVE。

LLM每样本一次调用，禁止看结果后重采样。中断失败后新建整份run，不能跨attempt/run拼行；缓存回放标CACHED_PLAYBACK，不称新运行。temperature=0和seed并非确定性证明。Ollama每次运行前后核对已安装模型digest和推理配置，漂移整份失败；严禁运行中自动pull或同一READY版本换权重。

### 6.4 稳定性证据与分析模式

AnalysisCreate明确传evidence_mode及stability_report（nullable）。CONFIRMATORY的LLM比较须提交实际DEV报告，按`SHA256('stability-v1|42|'+sample_id)`升序（相同hash按sample_id UTF-8排序）冻结前100个DEV样本；DEV不足100不满足该门禁。每模型3次完整新推理，run_id各异、各100行合法标签，同一模型每个sample_id的3次标签须完全相同；每轮附run_manifest且cache_mode=FRESH_INFERENCE，run_id和各identity匹配；DEV稳定性scope_hash为canonical {evaluation_data_sha256, protocol_version, selected_sample_ids}摘要。不是把重复300行当300独立样本。两模型的ID集合、dataset/weights/inference/app指纹匹配。报告JSON见stability-report.schema.json，直接嵌入AnalysisCreate，不接受客户端本地文件路径或孤立hash。服务器验证并存受限Artifact，生成stability_manifest_sha256。BUILTIN_TFIDF固定环境确定性对照可传null。缓存不能作为稳定性重复；外部报告需在运行记录中声明fresh，服务器验证一致性而不独立认证其真实性。

稳定性不通过/未做仍可DESCRIPTIVE_ONLY：仅D成对描述/候选，SUCCEEDED/INCONCLUSIVE、summary_reason=EVIDENCE_NOT_CONFIRMABLE，C全部null，POST confirm返回409且不消耗C。稳定DEV也不证明所有测试输出确定、更不证明权重变化导致了语义根因；只支持按冻结观测预测执行本协议。TRAINING_UPDATE比较还须同推理identity且实际不同weights；否则变更类型另报。

## 7. 数据可见性与复用

- TRAIN/DEV供训练和开发。D供分组、界面案例、套件构建。
- C的ID/text供预测worker或受审计的管理员输入导出读取；gold和成对结果只供确认worker。UI仅确认聚合。每次固定候选后一次确认，不在C调特征或改规则。
- A只供11的最终实验；网页接口不能浏览A。发现A数据问题可以停止实验并报告，不能修复算法后继续称同一盲测。
- 同数据版本多次模型迭代会逐渐适配测试集；报告须列确认次数和用途，不声称永久统计保证。
- 公共数据可能已在预训练中出现；本项目评价模型更新行为，不能据此论证模型从未见过样本。


### 原始响应与解析标签一致性

InferenceIdentity必须冻结parser_version：GREEDY_LABEL_TRIE/OLLAMA_JSON_SCHEMA使用label-json-v1，CLASSIFIER_ARGMAX使用label-literal-v1。JSON解析仅接受单对象且只有label键，其值在冻结label_vocab；literal按原始标签精确匹配，不trim猜测映射。raw_response必须非空，服务器按登记解析器重算标签并与prediction_label一致，不一致整批拒绝RAW_LABEL_MISMATCH；raw为实际返回的最终内容，provider思考字段若有单列工件，不拼造最终JSON。JSON Schema只校验形状，方法/解析器对应与动态label须业务验证。
