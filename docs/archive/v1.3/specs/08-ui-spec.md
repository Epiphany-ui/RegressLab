# 页面与交互规格

原概念界面只用于讨论，不作为已实现代码或性能证据。实现采用Vue3/TypeScript；桌面优先，最低宽度360px，表格可横向滚动但主要操作不可被遮挡。

## 1. 信息架构

```text
工作台
├─ 项目列表 /projects
└─ 项目 /projects/:projectId
   ├─ 概览
   ├─ 数据版本 /datasets
   ├─ 模型版本 /models
   ├─ 升级检查 /analyses
   ├─ 回归套件 /suites
   └─ 后台任务 /jobs
```

全局壳：左侧项目导航；顶部项目名称、当前数据版本、连接状态；内容区面包屑、标题、主要操作。创建/确认等高影响操作每屏最多一个主按钮。不使用LLM聊天框作为主页。

## 2. 页面合同

| 页面/route | 主要内容 | 操作/接口 | 空态与异常 |
|---|---|---|---|
| /access | 访问令牌输入 | 内存保存token，health后请求projects | 401保留目的路由、清token；无自动默认口令 |
| /projects | 名称/版本数/最近任务/归档 | 创建项目、进入 | 无项目给“创建第一个项目” |
| /projects/:p/datasets | 版本/状态/role计数/标签数/hash短码 | 上传canonical、查看manifest | 导入失败显示行号/总错误/修正后新建 |
| /datasets/:id | 来源许可、独立组件计数、分区、标签 | TRAIN/DEV/D案例分页 | C/A仅计数；禁止查看按钮 |
| /projects/:p/models | kind/状态/训练版本/配置/hash | CPU对照训练/检查已安装Ollama/注册离线微调预测来源 | 没有READY数据时引导导入 |
| /models/:id | 父版本/变更类型、权重与推理指纹、来源验证标志、CPU作业或离线训练清单 | 创建D+C预测集、复制run_id/导出inputs、上传预测与run_manifest | PRECOMPUTED显“仅导入预测，不能本地执行” |
| /projects/:p/analyses/new | 旧新完整预测集、变更类型、证据模式、固定协议说明 | 创建分析 | 不完整/失败项不可选；LLM可确认模式须提交DEV稳定性JSON；不自动标签映射 |
| /analyses/:id | 阶段、D总览、slice列表、确认聚合 | 查看证据、确认、生成套件、导出 | 无候选/确认不足/失败各有文案 |
| /suites/:id | 样本量、预算、义务覆盖、未覆盖项 | 查看选中项、导出、重放 | 没有旧正确样本时不展示假套件 |
| /replays/:id | 目标模型、执行状态、verdict、失败例 | 查看结果/需要时上传SUITE预测 | 执行错误单独ERROR |
| /projects/:p/jobs | kind/state/progress/attempt/耗时 | 取消、查看错误、允许时恢复 | 明确cancel_requested与已停止不同 |

## 3. 分析详情布局

第一行：旧/新模型名、数据版本、协议版本、D和C的范围，不只展示一个总准确率。

第二行：D整体准确率变化、distinct负向翻转数、正向翻转数。指标悬浮说明各分母；null显示“无可用分母”。

第三行：候选分组表。列：条件、D样本数/下降、C独立支持量/下降、修正p值、统计状态、人工关注。排序由服务器rank固定，UI筛选不改变检验家族。

侧边或下方证据面板：D原文、gold、新旧预测（明确展开才请求include_raw=true查看原始响应，全部转义）、四格归类、表面特征、分组成员、来源ID。可设置人工备注；不能编辑gold或“手动确认显著”。

DESCRIPTIVE_ONLY页面顶部固定标“仅描述：未达到可确认门禁”，结束后可导出D报告，C指标均为“未执行”，没有确认按钮；PROPOSED显示“发现集候选，未执行独立确认”。CONFIRMATORY确认按钮仅AWAITING_CONFIRMATION可用，确认对话框显示：候选数、candidate_set_hash短码、C一次使用说明、固定alpha和阈值。用户确认后只触发同一Analysis。

## 4. 强制文案

| 状态 | 显示文案 |
|---|---|
| PROPOSED | 发现集候选，尚未独立确认 |
| CONFIRMED_REGRESSION | 确认存在净退化；达到本次检验与幅度门槛 |
| NOT_CONFIRMED | 本次未确认退化，不等于已证明无退化 |
| INSUFFICIENT_SUPPORT | 独立确认样本不足，无法据此下结论 |
| NO_CANDIDATES | 发现阶段没有满足条件的分组，未使用确认集 |
| REVIEW_REQUIRED | 存在确认退化，建议人工审查升级风险 |
| NO_CONFIRMED_REGRESSION | 本协议下未确认退化；不是安全或非劣认证 |
| INCONCLUSIVE | 证据不足，不能给出全面结论 |
| Replay PASS | 本回归套件通过；不代表所有业务通过 |
| Replay ERROR | 执行/数据错误，尚无有效测试结论 |

负向变化用“下降5个百分点”，不能把0.05误写为“下降5%”又混用相对变化。C bootstrap区间旁写“描述性近似区间，未做多组同时覆盖修正”。

## 5. 套件与重放交互

选择预算后展示：原候选池/截断池、实际suite_size、覆盖义务权重比例、未覆盖义务。每个样本可查看选择理由。P0不可勾选删除已READY项目；用户想改则“基于当前结果创建新版本”。

重放目标下拉仅同项目、同labelset、READY模型。PRECOMPUTED提交后显示下载scope ID清单和上传入口；该清单包含suite文本与样本ID，但gold不进入分类器请求；导出suite给测试维护者本身可以包含gold。不能混淆测试者与被测模型输入。

## 6. 前端状态管理与错误恢复

Pinia只保存当前项目和导航状态；服务器资源为事实来源。HTTP层统一加token/request_id/幂等key，POST重试复用原key。token只在内存，刷新重新输入；不存localStorage、URL、报告或日志。

表单字段级422显示在对应输入；409显示原因与可操作下一步。网络断开不把作业标失败；重连GET状态。离开页面不取消后台任务；须主动取消。结果导出先请求完成状态，避免下载一份不完整报告。

生成解释不列为页面计划。旧解释资源只在兼容维护工具读取；页面不显示启用按钮，避免误认为仍需DeepSeek API才能验收。

## 7. 可访问性与验收

输入有label；按钮有文字；键盘顺序自然；色彩之外同时显示状态词；加载态有文字；表格标题明确；长文本折叠后可展开。Playwright检查创建项目到重放全流程，以及360/1024宽度关键操作可见。开发时以真实后端数据呈现，禁止生产页面硬编码“提升率”或演示成功。

## 8. 本地模型和训练来源交互

模型页三个入口：①内置CPU对照训练；②连接固定本机Ollama，读取已安装白名单、检查digest/兼容性后注册，不提供下载/安装/任意URL；③导入离线Transformers微调模型来源，填写父版本/step/base revision，上传文本形式的来源清单和日志，页面显著标“外部声明，未独立验证权重”。不提供LoRA训练按钮或GPU训练调度页面。未知API权重显示“未公开”，不可用占位hash填表通过。

详情同时展示weights_sha256和应用content_sha256，避免把提示词改动称权重升级。TRAINING_UPDATE必须说明哪里训练、用了哪个TRAIN子集、保存哪个checkpoint；REFERENCE无父的原因明确显示。预测页同时显示legal/expected、missing/invalid/failed和执行耗时，失败时不显示虚构准确率或通过结论；整轮重跑会创建新run_id。缓存显示“历史回放”，不能显示成新推理。

稳定性JSON只包含DEV ID/预测标签及hash，不展示C/A原始响应。模型切换过程中加载状态可见，不承诺6GB必定装下。Ollama缺失时显示安装由用户完成的说明，软件不能自行执行安装命令。
