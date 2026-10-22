"""Script-free exports containing only discovery evidence."""

import json
from html import escape


def report_payload(record: dict) -> dict:
    return {
        "report_schema": "regresslab-demo-report-v1",
        "analysis": record["public"],
        "discovery_cases": record["cases"],
    }


def render_html(record: dict) -> str:
    p = record["public"]
    m = p["metrics"]["discovery"]
    esc = lambda value: escape(str(value), quote=True)
    pct = lambda value: "无可用分母" if value is None else f"{value * 100:.2f}%"
    cases = "".join(
        "<tr>" + "".join(f"<td>{esc(row[k])}</td>" for k in (
            "sample_id", "text", "gold_label", "old_prediction_label", "new_prediction_label", "outcome"
        )) + "</tr>" for row in record["cases"]
    )
    limitations = "".join(f"<li>{esc(x)}</li>" for x in p["limitations"])
    source = "合成工程夹具" if p["fixture_only"] else "用户导入 · 外部声明"
    metrics = "".join(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>" for label, value in [
        ("D 样本数", m["n"]), ("双方正确 a", m["a"]), ("旧对新错 b", m["b"]),
        ("旧错新对 c", m["c"]), ("双方错误 d", m["d"]),
        ("旧版准确率", pct(m["old_accuracy"])), ("新版准确率", pct(m["new_accuracy"])),
        ("准确率下降", f'{m["accuracy_drop"] * 100:.2f} 个百分点'),
        ("负向翻转率 b/n", pct(m["negative_flip_rate"])),
        ("正向翻转率 c/n", pct(m["positive_flip_rate"])),
        ("旧正确样本退化率 b/(a+b)", pct(m["old_correct_regression_rate"])),
        ("旧版 Macro-F1", pct(m["old_macro_f1"])), ("新版 Macro-F1", pct(m["new_macro_f1"])),
    ])
    public_json = esc(json.dumps(p, ensure_ascii=False, indent=2, allow_nan=False))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(p['name'])} · RegressLab</title><style>
body{{font:15px/1.7 system-ui,sans-serif;color:#182c40;max-width:1100px;margin:40px auto;padding:0 24px}}
h1{{font-size:30px}}h2{{margin-top:32px}}.badge{{background:#e9eefb;padding:8px 14px;border-radius:8px}}
table{{border-collapse:collapse;width:100%;margin:16px 0}}th,td{{border:1px solid #dfe5ed;padding:10px;text-align:left;overflow-wrap:anywhere}}
th{{background:#f3f6fb}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6fb;padding:20px}}
.table-wrap{{overflow-x:auto}}small{{color:#56677b}}@media print{{body{{margin:0;max-width:none}}}}
</style></head><body><small>REGRESSLAB / DEMO REPORT</small><h1>{esc(p['name'])}</h1>
<p class="badge">{source} · DESCRIPTIVE_ONLY · INCONCLUSIVE</p>
<p>{esc(p['old_model']['name'])} → {esc(p['new_model']['name'])} · {esc(p['created_at'])}</p>
<p>仅分析发现集 D；未执行独立确认 C。分组表示关联，不能据此推断根因；未发现退化不代表安全。</p>
<h2>发现集成对指标</h2><table>{metrics}</table>
<h2>证据范围与限制</h2><ul>{limitations}</ul>
<h2>发现集样本</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>文本</th><th>Gold</th><th>旧预测</th><th>新预测</th><th>成对结果</th></tr></thead><tbody>{cases}</tbody></table></div>
<h2>配置、分组、混淆变化与来源指纹</h2><pre>{public_json}</pre>
<small>报告指纹 {esc(p['content_sha256'])} · 此文件不包含确认集/审计集原文或原始响应。</small>
</body></html>"""
