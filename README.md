# RegressLab · 模型退化诊断 Demo

本地中文工作台：导入标注数据和两版分类预测，严格校验完整性，计算发现集 D 的成对指标、候选分组与混淆变化，查看逐条证据并导出 JSON / HTML。分析结果保存在本机，刷新或重启后可以继续查看。

当前交付为 **0.1.0 描述性 Demo**。原始 1.3 设计、机器合同和教师 Word 已复制到本目录；原文档入口保留在 [DOCUMENTS.md](DOCUMENTS.md)，完整产品定义见 [PRODUCT.md](PRODUCT.md)。主实验仍为小模型真实微调更新，逻辑回归重新训练为对照；本 Demo 尚未执行这些训练或正式效果实验。

## 启动

需要 Python 3.11+、uv 和 Node 24。首次准备需要联网安装依赖；依赖和构建产物准备好后，启动与夹具演示无需联网。

```bash
bash scripts/setup.sh
bash scripts/demo.sh
```

浏览器访问 **http://127.0.0.1:8080**。自定义端口：`REGRESSLAB_PORT=8090 bash scripts/demo.sh`。停止时按 Ctrl+C。

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

命令适用于当前 Linux / WSL 工作区。前端开发：在一个终端运行 Demo，在另一个终端执行 `cd frontend && npm run dev`，访问 http://127.0.0.1:5173；Vite 将 API 与示例文件代理到 8080。

## 三分钟演示

1. 点击“载入工程夹具”，真实运行导入和分析。12 条 D 样本应为 a=6、b=3、c=1、d=2；旧准确率 75%，新准确率 58.3%，下降 16.7 个百分点。小夹具低于分组支持量 30，因此没有候选。
2. 切换“负向翻转”，查看 3 条旧对新错，分页或展开文本。
3. 载入分组发现夹具：D=96，能以固定生产门槛产生候选。合成夹具用于检验软件，不代表真实模型效果。
4. 下载格式示例，用“导入预测对比”上传数据和两份预测。缺失、重复、多余 ID、未知标签、混合 run 或原始响应不一致都会阻止分析。
5. 导出 JSON 或 HTML，刷新页面，在历史分析中重新打开。

格式和精确预期见 [examples/README.md](examples/README.md)。界面仅展示 D 逐例证据；C/A 不参与当前统计或分组，确认字段始终为 null。来源固定为 `DECLARED`，不认证外部推理和权重。有限样本和“未发现退化”都不代表模型安全。

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
node verification/check-package.cjs
```

后一个命令仅验证原设计文档与合同，不能代替应用或模型实验验收。当前实现范围和后续任务见 [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)，API 约定见 [docs/DEMO-API.md](docs/DEMO-API.md)，实测记录见 [docs/VALIDATION.md](docs/VALIDATION.md)。界面规范见 [DESIGN.md](DESIGN.md)。

## 数据与当前边界

默认数据文件为 `var/demo.sqlite3`，包含成功导入的原文和预测，目录已从 Git 排除。`REGRESSLAB_DATA_DIR` 可指定另一个目录。所有成功结果只追加，读取时核对完整记录指纹。停止服务后可备份整个 `var` 目录；恢复到新目录再运行 doctor。失败上传只留输入摘要和错误码，不保存失败原始文件。

此 Demo 使用 SQLite 和有界同步导入，单份文件 ≤10 MiB、数据 ≤5000 行，仅绑定 `127.0.0.1`。这是有意缩小的前期实现，API 独立使用 `/api/demo`，未冒充最终 `/api/v1` 或完整报告合同。最终 PostgreSQL、持久队列/Worker、认证、模型来源登记、GPU微调/Ollama、DEV稳定性、C一次确认、冻结套件和真实后续版本重放尚待后续阶段完成。不要把此入口用于公网部署。

---

原始设计包说明已完整保留于 [DOCUMENTS.md](DOCUMENTS.md)。
