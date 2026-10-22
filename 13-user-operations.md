# 用户、运维与答辩手册

这是未来实现的操作合同，当前文档包不等于已安装系统。启动入口必须由M01/M10实现并实测。

## 1. 首次使用

1. 按10启动服务，访问本机8080；输入部署者生成的APP_TOKEN。
2. 创建项目“中文意图模型升级检查”。
3. 从官方仓库入口获取MASSIVE1.1，保存LICENSE和实际文件hash；使用`python -m regresslab.cli convert-massive --input <zh-CN.jsonl> --output <canonical.jsonl>`转换。
4. 在数据页面上传canonical与来源许可；等待READY，查看各分区、独立组件计数和标签表。若INVALID先修数据，不继续训练。
5. 主实验按19先做32步训练烟测，确认0.6B在实际6GB环境可训练后，固定recipe与TRAIN子集，保存step100/200/300的v1/v2/v3、真实日志/权重manifest；不要把原始base和不同后端版本拼成“优化前后”。CPU对照可分别用TRAIN的0.5/0.8/1.0嵌套子集重新训练，C=1、seed42、特征设置固定。两条链均不预设越新越好。
6. 先注册历史v1、候选v2为PRECOMPUTED并提交真实来源清单（明确DECLARED），父版本/step/权重hash可追溯；离线主链固定Transformers/PEFT推理。分别创建D+C预测集，按server run_id导出inputs，输出含raw_response的完整单轮预测和run_manifest，上传并等待SUCCEEDED。v3只注册元数据不查看其D/A结果，冻结套件后再运行。Ollama入口用于另一次真实本地推理验收：由用户提前安装官方支持模型，页面检查digest/白名单后注册，无需或强迫转换主LoRA链。
7. 按03对v1/v2做固定100 DEV样本×各3轮重复，生成stability_report。创建CONFIRMATORY分析时直接提交报告；稳定性失败/缺失则改用DESCRIPTIVE_ONLY，仅D描述且C不执行。合法可确认分析阅读D后使用冻结家族一次C。任何模式均不把执行错误、漏行或缓存重复当作有效统计证据。
8. 生成预算50的套件，查看实际size/未覆盖项并导出；对v2重放，查看PASS/FAIL/ERROR与逐例证据。
9. 导出分析报告和suite，保留来源、版本与hash，不只截一张分数图。

外部预测输入准备命令：`python -m regresslab.cli prediction-inputs --prediction-set-id <id> --output <inputs.jsonl>`。CLI只导出sample_id,text，不含gold/role/features；roles scope会包含C文本供被测分类器推理，该管理员命令不等于网页可浏览C标签。保持C输出不参与手工调参，使用记录写审计。SUITE输入来自D，可在套件页导出输入清单。

## 2. 如何读结果

“整体提高”仍可能出现旧对新错；同一个错误可在多个分组中重复出现。分组里的词法条件是关联，不代表根因。NOT_CONFIRMED不等于安全，INSUFFICIENT_SUPPORT不是成功。若无候选，系统仍完成了一次合法检查，不需要人为造退化。

回归套件只保证其中样本可重放。新模型PASS不能替代完整业务评测，也不能证明C/A上没有问题。不要把suite拿来训练目标模型后，再声称对同suite的PASS反映泛化。

## 3. 常见故障

| 现象 | 检查 | 操作 |
|---|---|---|
| 上传INVALID | 错误行、重复ID、gold冲突、官方分区泄漏 | 修改源文件，新建版本；不改已封存数据 |
| 训练FAILED | TRAIN是否覆盖全部标签、内存/超时、锁文件 | 修配置后新建ModelVersion，不复用内容身份 |
| 预测覆盖错误 | scope_hash/run_id与预期ID集合、raw_response与run_manifest | 重新导出inputs并整轮生成预测，新建PredictionSet；不拼接旧成功行 |
| 等待确认 | Analysis正常状态 | 查看D后确认，或保留探索结果 |
| 确认已使用 | 同一模型内容对已有Analysis | 查看原结果，不换一个ID绕过一次性限制 |
| 长时间排队 | worker心跳/单任务状态 | 查看jobs；不反复点创建；必要时取消旧任务 |
| worker崩溃 | lease/attempt日志 | 等自动恢复；超过3次人工排查后对原确定性资源resume |
| Replay等待输入 | PRECOMPUTED没有可执行模型 | 上传SUITE scope预测；不能认为系统已测试 |
| 报告下载409 | 作业未完成或失败 | 修复失败/等待完成；不下载半成品 |
| Ollama无模型/不兼容 | 安装白名单、固定端点、digest、结构化输出/think支持 | 用户自行安装受支持模型后新注册；应用不自动下载 |
| MODEL_IDENTITY_DRIFT | 运行前后digest/后端/提示词指纹 | 保留失败run；注册新版本，不修改READY版本 |
| 只能描述/无法确认 | DEV重复不一致、稳定性报告缺失或来源不匹配 | 停止确认；在DEV排查/冻结新配置或仅报告描述结果 |
| 生成解释不可用 | FEATURE_DISABLED | 旧兼容路由，本版不计划实现 |

## 4. 维护命令合同

`doctor`只读检查加临时存储写测试；`verify-artifacts`逐个hash核对；`jobs inspect <id>`读状态；`jobs resume-analysis <analysis-id>`走同API约束；`gc-orphans --dry-run`只列无人引用且超过24小时的文件；实际清理由维护者单独操作，不在训练期间自动递归删除目录。

## 5. 答辩演示（建议8—10分钟）

1. 1分钟：说明平均分与升级兼容性区别，展示真实模型/数据版本。
2. 2分钟：展示D发现、旧对新错证据和可解释条件；条件不称根因。
3. 2分钟：展示一次独立确认、修正p值、样本不足与非安全认证文案。
4. 2分钟：生成/查看套件，对第三版本实际重放，打开一个失败用例。
5. 1分钟：导出报告/hash，展示worker恢复或自动测试记录。
6. 1分钟：说明相近工具已有能力、自己实现的机制和实验结果/负结果。

提前缓存真实数据/模型/依赖，下载和部署就绪后本地Ollama/主预测导入可断网运行；用小规模真实任务保证演示耗时可控。备用合成夹具必须明确标注“工程演示”，不能冒充真实实验效果。

## 6. 证据留存和演示诚实性

保存真实训练日志、checkpoint文件manifest、依赖锁、base/tokenizer revision、TRAIN子集清单、每轮推理raw响应/run_manifest、稳定性报告、冻结suite和后续模型结果。每份运行标FRESH_INFERENCE或CACHED_PLAYBACK，缓存只用于恢复查看，不是额外独立实验。外部导入页面“声明来源”不等于软件独立验证了权重。API若选做只作补充，不冒充可由我们调权重的模型链。

同一数据重新上传/改source_version不重置确认次数：使用不含来源元数据的evaluation_data_sha256核对。正式预处理选择必须发生在模型结果之前；遇到跨官方分区重复先审计停止。若预先选择清理profile，转换命令增加`--exclude-cross-partition-components`，剔除整个泄漏/冲突组件（包括TRAIN/DEV/TEST相关行），保留exclusion_manifest和hash，数据名标“cleaned MASSIVE subset”，确认全部60个意图仍在TRAIN且gold合同合法。不得只删表现差的测试行，或把测试文本搬进训练。
