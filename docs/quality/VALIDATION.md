# Demo 验证记录

此文件记录应用级实际检查；[设计验证目录](../archive/v1.3/verification/README.md)保留设计阶段的静态检查与审阅。合成夹具验证软件行为，不证明模型效果或研究结论。

验收日期：2026-10-23（Asia/Shanghai）。实际环境：Linux 6.18.33.2-microsoft-standard-WSL2、Python 3.14.4、Node 24.19.0、npm 12.2.1；浏览器使用环境已安装的 Chromium，依赖版本由三份锁文件固定。Python 3.11为兼容目标，此次没有另起3.11环境验证。

## 实际结果

| 检查 | 结果 | 覆盖范围 |
|---|---|---|
| `backend/.venv/bin/python -m pytest -q`（在backend目录运行时去掉backend前缀） | 67 passed | 35领域＋32 API集成测试 |
| `cd frontend && npm run typecheck` | PASS | Vue/TypeScript静态类型 |
| `cd frontend && npm run build` | PASS | Vite生产构建，JS约110kB、CSS约63kB，均未压缩尺寸 |
| `cd e2e && npm test`（指定已安装Chromium） | 6 passed，约11秒 | 1440×1000桌面与360×800移动端，各3个流程 |
| `node scripts/check-design.cjs`（仓库根目录） | 17组全部PASS | 原设计、Schema、公式与追踪静态检查；当前入口名称 |
| `backend/.venv/bin/python -m regresslab.cli doctor` | SQLite ok、历史hash通过、前端已构建 | 本机实际数据目录检查 |
| 原包首次导入SHA256对比（历史记录） | 48份均已导入；46份原文一致 | 首次导入时的记录；原README现见[设计总目录](../archive/v1.3/specs/README.md)，当时仅校验器及静态检查记录有意更新 |

后端使用FastAPI TestClient及临时SQLite。当前受限执行环境会阻塞异步测试客户端的线程唤醒，改在获准的沙箱外运行后通过；纯领域测试可直接在沙箱内运行。测试出现Starlette对httpx测试适配器的未来弃用提示，不影响本次结果。

浏览器测试自行启动8081端口，使用全新临时数据库，与供用户体验的8080数据目录分离。覆盖工程夹具、四格与准确率核对、候选默认门槛、负向筛选/分页、JSON/HTML真实下载、刷新恢复、multipart真实上传、缺行拒绝后修正重传、来源字段、默认分组、移动布局无页面溢出，以及慢历史请求期间阻止并发导入。手机证据面板逐字竖排问题已修复，并加入三行全宽布局及44px主按钮检查。

API检查还覆盖同group/同文本传递泄漏、未知标签、重复JSON键/非有限值、同run约束、raw重解析、缺失/重复/额外ID、C/A案例拒绝、描述模式确认409、失败不新增成功记录、跨站写入、按实际字节限制、HTML注入转义、存储损坏拒绝、重启后读取与hash核对。独立代码审查发现的历史请求覆盖新建分析问题已修复，并通过慢请求场景验收。

界面实测截图：[桌面](../screenshots/demo-desktop.png)、[360px移动端](../screenshots/demo-mobile.png)。截图仅包含合成工程数据。

## 目录整理与复验（2026-10-23）

设计正文、机器合同、界面约定和验收记录已按用途归入`docs/specs`、`docs/contracts`、`docs/design`和`docs/quality`；静态校验脚本现为`scripts/check-design.cjs`。原包48份/46份一致的数量保留为首次导入历史，不作为路径及说明维护后的逐字节一致性结论。目录整理不改变上述软件验收的范围和研究证据边界。

| 整理后检查 | 结果 |
|---|---|
| 后端领域与API测试 | 67 passed |
| 合成夹具重新生成 | 7个输出工件逐字节一致 |
| 本机doctor与HTTP健康接口 | 通过 |
| `node scripts/check-design.cjs`（仓库根目录） | 17/17通过，覆盖31份Markdown |
| 文档与夹具说明的本地链接核验 | 30份Markdown、118个目标均存在 |

本次目录整理没有修改界面，未重跑浏览器测试；上方6条浏览器通过结果及截图保留为整理前的验收记录。

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

真实MASSIVE下载、GPU训练/显存和恢复、真实模型推理、DEV稳定性、一次C确认、套件/未来版本重放、PostgreSQL/Worker恢复部署、正式实验和算法增益均未执行。当前成功仅证明此Demo在上述检查范围内可用；不是P0成品或研究效果验收。完整后续顺序见 [IMPLEMENTATION.md](../development/IMPLEMENTATION.md)。

## v2迁移后的历史路径说明

上述代码/浏览器和第一次目录整理结果保留为历史记录。v2规划归档后，旧规格/合同/验证移至`docs/archive/v1.3/`，旧检查入口改为`node scripts/check-legacy-design.cjs`；当时记录中的`check-design.cjs`不是当前命令。当前规划与本轮实际复验另见[V2-PLANNING-VALIDATION.md](V2-PLANNING-VALIDATION.md)。
