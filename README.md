# RegressLab · 文本分类回归选样研究

当前研究方向是**《基于历史群体风险的文本分类模型回归测试样本选择方法研究》**：利用f0/f1/f2的历史，在执行目标f3前选出有限预算测试集，比较HGC与强基线的未来负向翻转检出和成本。HGC是待验证候选；第二轮固定配置在当前CPU开发设置中未显示收益。

**已完成两轮真实CPU开发预实验；Web仍为0.1描述性Demo。** 第二轮修复模型复用检查，完成24次训练、6条四版链、9基线＋固定HGC，共2,064个单元。HGC在B=100时Recall为0—0.50，margin为0.80—1.00；当前缓存情景中HGC总成本为全P推理的11—15倍，三项开发筛查均未通过。详见[第二轮报告](docs/experiments/cpu-preflight-v2/README.md)、[开发日志](docs/development/logs/2026-10-24-cpu-preflight-v2.md)及[首轮记录](docs/experiments/cpu-preflight-v1/README.md)。保留负结果，不再追加第三轮同DEV寻优；先做机制诊断与独立数据审计，再决定研究范围。

从 [研究资料](docs/research/v2/README.md)、[工程设计与实施计划](docs/engineering/v2/README.md) 或 [统一文档导航](docs/README.md) 开始。8份源Markdown逐字节保留；源包未附其引用的Word，差异见[导入清单](docs/research/v2/import-manifest.json)。

## 项目结构

```text
RegressLab/
├── README.md                  # 当前方向与可运行Demo入口
├── backend/                   # 已实现：0.1 Demo API与测试
├── frontend/                  # 已实现：中文工作台；研究证据展示待扩展
├── e2e/                       # 已实现：Demo浏览器测试
├── examples/                  # 已实现：v1合成夹具，不是v2实验结果
├── lab/                       # 本次规划：离线选择/冻结/评测，尚无算法代码
├── experiments/               # 已实现：独立CPU预实验、最小HGC、基线、冻结与结果复核
├── scripts/                   # 启动、夹具、当前文档/历史合同校验
└── docs/
    ├── research/v2/           # 新研究原文与来源清单
    ├── engineering/v2/        # 新软件设计、工件Schema与开发规划
    ├── development/           # 当前实现状态、开发日志与v1 Demo实际接口
    ├── experiments/           # 真实预实验报告及轻量审计工件
    ├── archive/v1.3/          # 被取代的规格、合同与应用建设计划
    ├── design/                # 沿用的视觉规范与研究展示补充
    ├── quality/               # Demo历史验收与本轮规划检查
    └── screenshots/           # 原Demo截图
```

本地运行数据`var/`、完整研究工件`artifacts/`、原始数据`datasets/`、模型`checkpoints/`及依赖/缓存被Git排除。`lab/`仍为计划目录；CPU预实验的实际运行命令见[experiments](experiments/README.md)，计划中的`regresslab_experiments.cli`尚未实现。

## 启动现有兼容 Demo

需要 Python 3.11+、uv 和 Node 24。首次准备需要联网安装依赖；依赖和构建产物准备好后，启动与夹具演示无需联网。

```bash
bash scripts/setup.sh
bash scripts/demo.sh
```

浏览器访问**http://127.0.0.1:8080** 。自定义端口：`REGRESSLAB_PORT=8090 bash scripts/demo.sh`。停止时按 Ctrl+C。

也可分步启动：

```bash
cd backend
uv sync --frozen --cache-dir ../.cache/uv
cd ../frontend
npm ci --cache ../.cache/npm
npm run build
cd ..
backend/.venv/bin/python -m regresslab.cli demo --port 8080
```

前端开发：在一个终端运行 Demo，在另一个终端执行 `cd frontend && npm run dev`，访问 http://127.0.0.1:5173；Vite 将 API 与示例文件代理到 8080。

## 三分钟演示

1. 点击“载入工程夹具”，真实运行导入和分析。12 条 D 样本应为 a=6、b=3、c=1、d=2；旧准确率 75%，新准确率 58.3%，下降 16.7 个百分点。小夹具低于分组支持量 30，因此没有候选。
2. 切换“负向翻转”，查看 3 条旧对新错，分页或展开文本。
3. 载入分组发现夹具：D=96，能以固定生产门槛产生候选。合成夹具用于检验软件，不代表真实模型效果。
4. 下载格式示例，用“导入预测对比”上传数据和两份预测。缺失、重复、多余 ID、未知标签、混合 run 或原始响应不一致都会阻止分析。
5. 导出 JSON 或 HTML，刷新页面，在历史分析中重新打开。

格式和精确预期见 [examples/README.md](examples/README.md)。当前Demo仍按v1的50/25/25划分和D+C覆盖运行，不能自动当成v2的80/10/10实验或四版历史。C/A不参与当前统计或分组，来源固定为`DECLARED`；合成夹具不是模型效果证据。

## 验证与开发

```bash
cd backend && .venv/bin/python -m pytest -q
cd ../frontend && npm run build
cd ../e2e && npm ci --cache ../.cache/npm
npx playwright install chromium
npm test
```

浏览器测试会使用独立临时数据库并启动本地服务，包含桌面/360px移动布局、夹具、真实上传、负例与导出。已安装的 Chromium 可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指定。

```bash
backend/.venv/bin/python -m regresslab.cli doctor
backend/.venv/bin/python scripts/check-docs.py
node scripts/check-legacy-design.cjs
```

`check-docs.py`核对来源摘要、文档链接和v2合同草案；源包缺失的Word会明确报告为已知警告。历史校验器只检查归档的v1.3包。两者都不证明研究方法已实现或实验有效。当前状态见[实施进展](docs/development/IMPLEMENTATION.md)，实际接口见[Demo API](docs/development/DEMO-API.md)，原软件验收见[记录](docs/quality/VALIDATION.md)，本轮规划验收另见[v2记录](docs/quality/V2-PLANNING-VALIDATION.md)。

## 数据与当前边界

默认数据文件为 `var/demo.sqlite3`，包含成功导入的原文和预测，目录已从 Git 排除。`REGRESSLAB_DATA_DIR` 可指定另一个目录。所有成功结果只追加，读取时核对完整记录指纹。停止服务后可备份整个 `var` 目录；恢复到新目录再运行 doctor。失败上传只留输入摘要和错误码，不保存失败原始文件。

此Demo使用SQLite、有界同步导入及`/api/demo`，保持单份10MiB/5000行护栏和回环绑定。v2将由独立离线lab构造共同候选池、登记方法、冻结完整矩阵，再由评测器解封目标；Web只读取验证后的证据。PostgreSQL、多Worker、账号、完整Ollama/API和网页训练已暂缓，不能继续作为下一轮必做项。具体任务和G0—G3出口见[开发计划](docs/engineering/v2/07-implementation-plan.md)。
