# Demo 验证记录

此文件记录应用级实际检查；原verification目录记录设计静态检查。合成夹具验证软件行为，不证明模型效果或研究结论。

验收日期：2026-10-23（Asia/Shanghai）。实际环境：Linux 6.18.33.2-microsoft-standard-WSL2、Python 3.14.4、Node 24.19.0、npm 12.2.1；浏览器使用环境已安装的 Chromium，依赖版本由三份锁文件固定。Python 3.11为兼容目标，此次没有另起3.11环境验证。

## 实际结果

| 检查 | 结果 | 覆盖范围 |
|---|---|---|
| `backend/.venv/bin/python -m pytest -q`（在backend目录运行时去掉backend前缀） | 67 passed | 35领域＋32 API集成测试 |
| `cd frontend && npm run typecheck` | PASS | Vue/TypeScript静态类型 |
| `cd frontend && npm run build` | PASS | Vite生产构建，JS约110kB、CSS约63kB，均未压缩尺寸 |
| `cd e2e && npm test`（指定已安装Chromium） | 6 passed，约11秒 | 1440×1000桌面与360×800移动端，各3个流程 |
| `node verification/check-package.cjs` | 17组全部PASS | 原设计、Schema、公式与追踪静态检查 |
| `backend/.venv/bin/python -m regresslab.cli doctor` | SQLite ok、历史hash通过、前端已构建 | 本机实际数据目录检查 |
| 原包逐文件SHA256对比 | 48份均已导入；46份原文一致 | 原README在DOCUMENTS.md；仅校验器及静态检查记录有意更新 |

后端使用FastAPI TestClient及临时SQLite。当前受限执行环境会阻塞异步测试客户端的线程唤醒，改在获准的沙箱外运行后通过；纯领域测试可直接在沙箱内运行。测试出现Starlette对httpx测试适配器的未来弃用提示，不影响本次结果。

浏览器测试自行启动8081端口，使用全新临时数据库，与供用户体验的8080数据目录分离。覆盖工程夹具、四格与准确率核对、候选默认门槛、负向筛选/分页、JSON/HTML真实下载、刷新恢复、multipart真实上传、缺行拒绝后修正重传、来源字段、默认分组、移动布局无页面溢出，以及慢历史请求期间阻止并发导入。手机证据面板逐字竖排问题已修复，并加入三行全宽布局及44px主按钮检查。

API检查还覆盖同group/同文本传递泄漏、未知标签、重复JSON键/非有限值、同run约束、raw重解析、缺失/重复/额外ID、C/A案例拒绝、描述模式确认409、失败不新增成功记录、跨站写入、按实际字节限制、HTML注入转义、存储损坏拒绝、重启后读取与hash核对。独立代码审查发现的历史请求覆盖新建分析问题已修复，并通过慢请求场景验收。

界面实测截图：[桌面](screenshots/demo-desktop.png)、[360px移动端](screenshots/demo-mobile.png)。截图仅包含合成工程数据。

## 机械核对值

小夹具：总数据30、TRAIN8/DEV2/D12/C4/A4，两份预测各16，完整D+C合法覆盖。D：a6/b3/c1/d2，旧准确率0.75、新准确率7/12、下降1/6、NFR0.25，0候选。

大夹具：总数据234、TRAIN8/DEV2/D96/C96/A32，两份预测各192。D：a64/b24/c4/d4，旧准确率88/96、新准确率68/96，6个候选；否定特征组n48、下降0.5。候选均PROPOSED，C确认全部null，结论始终INCONCLUSIVE。生成脚本重跑7个输出工件逐字节一致。

## 锁文件摘要

```text
backend/uv.lock            3d93e40407f618b30dd254b352e6084249db7842adc84e18b2e9cf7b9b782357
frontend/package-lock.json 46bb230d78c86c7f64edf641e1a99f0d44af6a92f141d32b1e37f4adf8c736bb
e2e/package-lock.json      5f60f2a2a47a477fa81872779726c5150764df775489311f2bbc53cd970876ce
```

## 未执行的产品与实验工作

真实MASSIVE下载、GPU训练/显存和恢复、真实模型推理、DEV稳定性、一次C确认、套件/未来版本重放、PostgreSQL/Worker恢复部署、正式实验和算法增益均未执行。当前成功仅证明此Demo在上述检查范围内可用；不是P0成品或研究效果验收。完整后续顺序见 [IMPLEMENTATION.md](IMPLEMENTATION.md)。
