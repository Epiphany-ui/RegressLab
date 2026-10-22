<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api, ApiError, downloadReport } from './api'
import Icon from './Icon.vue'
import type { Analysis, AnalysisSummary, CasePage, Health, Outcome } from './types'

const health = ref<Health | null>(null)
const history = ref<AnalysisSummary[]>([])
const analysis = ref<Analysis | null>(null)
const cases = ref<CasePage>({ items: [], total: 0, page: 1, page_size: 6 })
const outcome = ref<Outcome>('all')
const loading = ref(true)
const casesLoading = ref(false)
const busy = ref(false)
const error = ref('')
const caseError = ref('')
const notice = ref('')
const activeSection = ref('overview')
const mobileNav = ref(false)
const exportOpen = ref(false)
const exporting = ref(false)
const modalOpen = ref(false)
const modal = ref<HTMLDialogElement | null>(null)
const modalError = ref('')
const modalErrorDetails = ref('')
const importForm = ref<HTMLFormElement | null>(null)
const importTrigger = ref<HTMLElement | null>(null)
let caseRequest = 0
let analysisRequest = 0

const form = ref({
  name: '', old_model_name: '', new_model_name: '', parser_version: 'label-json-v1',
  source_url: '', source_version: '', license: '',
})
const files = ref<Record<string, File | null>>({ dataset_file: null, old_predictions_file: null, new_predictions_file: null })
const m = computed(() => analysis.value?.metrics.discovery)
const pages = computed(() => Math.max(1, Math.ceil(cases.value.total / cases.value.page_size)))
const currentRows = computed(() => cases.value.total ? `${(cases.value.page - 1) * cases.value.page_size + 1}–${Math.min(cases.value.page * cases.value.page_size, cases.value.total)}` : '0')
const allCoverage = computed(() => {
  if (!analysis.value) return null
  const { old, new: newer } = analysis.value.coverage
  const expected = old.expected_count + newer.expected_count
  return expected ? (old.legal_count + newer.legal_count) / expected : null
})
const outcomes: { value: Outcome; name: string; short: string; cls: string; key: 'a' | 'b' | 'c' | 'd' }[] = [
  { value: 'both_correct', name: '双方正确', short: '双方正确', cls: 'stable', key: 'a' },
  { value: 'negative_flip', name: '旧对新错', short: '负向翻转', cls: 'negative', key: 'b' },
  { value: 'positive_flip', name: '旧错新对', short: '正向翻转', cls: 'positive', key: 'c' },
  { value: 'both_wrong', name: '双方错误', short: '双方错误', cls: 'wrong', key: 'd' },
]
const nav = [
  { id: 'overview', label: '诊断概览', icon: 'grid' },
  { id: 'groups', label: '候选分组', icon: 'layers' },
  { id: 'cases', label: '发现集证据', icon: 'search' },
  { id: 'data', label: '数据与来源', icon: 'database' },
]
const fileFields = [
  { key: 'dataset_file', title: '标注数据集', hint: 'Canonical JSONL · 包含 sample_id、text、gold_label、group_id、source_partition 与 locale' },
  { key: 'old_predictions_file', title: '旧版本预测', hint: '预测 JSONL · 完整覆盖 DISCOVERY 与 CONFIRM 样本' },
  { key: 'new_predictions_file', title: '新版本预测', hint: '预测 JSONL · 与旧版本使用相同 D+C scope 和标签表' },
]

function percent(value: number | null | undefined, digits = 1): string {
  return value == null ? '无可用分母' : `${(value * 100).toFixed(digits)}%`
}
function points(value: number | null | undefined): string {
  return value == null ? '无可用分母' : `${Math.abs(value * 100).toFixed(1)} 个百分点`
}
function date(value: string, compact = false): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('zh-CN', compact ? { month: '2-digit', day: '2-digit' } : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}
function shortHash(value?: string): string { return value ? `${value.slice(0, 12)}…` : '未提供' }
function outcomeName(value: Outcome): string { return outcomes.find(item => item.value === value)?.name || value }
function outcomeClass(value: Outcome): string { return outcomes.find(item => item.value === value)?.cls || '' }
function featureName(value: string): string {
  return ({ text_length_bucket: '文本长度', length_bucket: '文本长度', length_bin: '文本长度', locale: '语言地区', has_negation: '包含否定词', has_question_mark: '包含问号', gold_label: '正确标签', has_number: '包含数字', has_digit: '包含数字', has_latin: '包含拉丁字母', has_punctuation: '包含标点', punctuation_bucket: '标点数量' } as Record<string, string>)[value] || value
}
function message(err: unknown): string { return err instanceof Error ? err.message : '请求未完成，请稍后重试。' }

async function refreshHistory(): Promise<void> {
  const data = await api<{ items: AnalysisSummary[] }>('/analyses')
  history.value = data.items
}

async function initialize(): Promise<void> {
  loading.value = true
  error.value = ''
  const results = await Promise.allSettled([api<Health>('/health'), refreshHistory()])
  if (results[0].status === 'fulfilled') health.value = results[0].value
  else error.value = message(results[0].reason)
  if (results[1].status === 'rejected') error.value = message(results[1].reason)
  if (history.value[0]) await selectAnalysis(history.value[0].id)
  loading.value = false
}

async function selectAnalysis(id: string): Promise<void> {
  if (busy.value) return
  const request = ++analysisRequest
  ++caseRequest
  casesLoading.value = false
  caseError.value = ''
  loading.value = true
  error.value = ''
  try {
    const detail = await api<Analysis>(`/analyses/${encodeURIComponent(id)}`)
    if (request !== analysisRequest) return
    analysis.value = detail
    outcome.value = 'all'
    await loadCases(1)
  } catch (err) { if (request === analysisRequest) error.value = message(err) }
  finally { if (request === analysisRequest) loading.value = false }
}

async function loadCases(page = 1): Promise<void> {
  if (!analysis.value) return
  const request = ++caseRequest
  casesLoading.value = true
  caseError.value = ''
  try {
    const result = await api<CasePage>(`/analyses/${encodeURIComponent(analysis.value.id)}/cases?outcome=${outcome.value}&page=${page}&page_size=6`)
    if (request === caseRequest) cases.value = result
  } catch (err) { if (request === caseRequest) caseError.value = message(err) }
  finally { if (request === caseRequest) casesLoading.value = false }
}

async function loadFixture(kind: 'paired' | 'discovery' = 'paired'): Promise<void> {
  if (busy.value) return
  const request = ++analysisRequest
  ++caseRequest
  casesLoading.value = false
  loading.value = false
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const detail = await api<Analysis>(kind === 'discovery' ? '/fixture?kind=discovery' : '/fixture', { method: 'POST' })
    if (request !== analysisRequest) return
    analysis.value = detail
    outcome.value = 'all'
    await Promise.all([refreshHistory(), loadCases()])
    notice.value = '工程夹具已完成校验与计算。此结果仅验证软件流程，不代表真实模型实验。'
    go('overview')
  } catch (err) { error.value = message(err) }
  finally { busy.value = false }
}

function go(id: string): void {
  activeSection.value = id
  mobileNav.value = false
  nextTick(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

async function openImport(event?: Event): Promise<void> {
  if (busy.value || loading.value) return
  importTrigger.value = event?.currentTarget as HTMLElement | null
  modalError.value = ''
  modalErrorDetails.value = ''
  modalOpen.value = true
  await nextTick()
  modal.value?.showModal()
}
function closeImport(): void {
  if (busy.value) return
  modal.value?.close()
  modalOpen.value = false
  importTrigger.value?.focus()
}
function setFile(key: string, event: Event): void {
  const file = (event.target as HTMLInputElement).files?.[0] || null
  files.value[key] = file
}

async function submitImport(): Promise<void> {
  if (!importForm.value?.reportValidity() || busy.value) return
  modalError.value = ''
  modalErrorDetails.value = ''
  const payload = new FormData()
  for (const [key, value] of Object.entries(form.value)) payload.append(key, value.trim())
  for (const field of fileFields) {
    const file = files.value[field.key]
    if (!file) { modalError.value = `请选择${field.title}文件。`; return }
    if (file.size > (health.value?.limits.max_file_bytes || 10485760)) { modalError.value = `${field.title}超过单文件 10 MB 的限制。`; return }
    payload.append(field.key, file)
  }
  const request = ++analysisRequest
  ++caseRequest
  casesLoading.value = false
  loading.value = false
  busy.value = true
  try {
    const detail = await api<Analysis>('/analyses', { method: 'POST', body: payload })
    if (request !== analysisRequest) return
    analysis.value = detail
    outcome.value = 'all'
    await Promise.all([refreshHistory(), loadCases()])
    busy.value = false
    closeImport()
    notice.value = '文件已通过完整性校验，发现集分析已保存。来源为外部声明，未独立验证模型身份。'
    go('overview')
  } catch (err) {
    modalError.value = message(err)
    if (err instanceof ApiError && err.details) modalErrorDetails.value = typeof err.details === 'string' ? err.details : JSON.stringify(err.details, null, 2)
  } finally { busy.value = false }
}

async function exportAnalysis(format: 'json' | 'html'): Promise<void> {
  if (!analysis.value || exporting.value) return
  exporting.value = true
  exportOpen.value = false
  error.value = ''
  try {
    await downloadReport(analysis.value.id, format)
    notice.value = `${format.toUpperCase()} 报告已导出，包含证据模式、来源声明与结果边界。`
  } catch (err) { error.value = message(err) }
  finally { exporting.value = false }
}

onMounted(initialize)
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ 'mobile-open': mobileNav }">
      <a href="#overview" class="brand" @click.prevent="go('overview')" aria-label="RegressLab 首页">
        <span class="brand-mark"><svg width="25" height="25" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M7 25V7h9c9 0 9 11 0 11H7m9 0 10 7M24 6v8m-3-3 3 3 3-3" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg></span>
        <span>Regress<span class="brand-light">Lab</span><small>模型退化诊断工作台</small></span>
      </a>
      <div class="workspace-picker"><span class="workspace-avatar">R</span><div><strong>本地工作空间</strong><span>Local workspace</span></div><span class="pill tiny">DEMO</span></div>
      <p class="nav-label">工作台 <span>WORKSPACE</span></p>
      <nav aria-label="工作台导航">
        <a v-for="item in nav" :key="item.id" :href="`#${item.id}`" :class="['nav-item', { active: activeSection === item.id }]" :aria-current="activeSection === item.id ? 'page' : undefined" @click.prevent="go(item.id)"><Icon :name="item.icon" :size="19" /><span>{{ item.label }}</span><Icon v-if="activeSection === item.id" name="chevron" :size="14" /></a>
      </nav>
      <div class="history-heading"><p class="nav-label">最近分析</p><span class="count-neutral">{{ history.length }}</span></div>
      <div class="history-list" aria-label="历史分析">
        <p v-if="!history.length" class="history-empty">完成导入后，分析将保存在这里。</p>
        <button v-for="item in history.slice(0, 12)" :key="item.id" :class="['history-item', { selected: item.id === analysis?.id }]" :disabled="busy" @click="selectAnalysis(item.id)"><span class="history-dot" :class="{ fixture: item.fixture_only }"></span><span><strong>{{ item.name }}</strong><small>{{ item.fixture_only ? '工程夹具' : '导入预测' }}<span>·</span>{{ date(item.created_at, true) }}</small></span></button>
      </div>
      <div class="sidebar-bottom"><div class="demo-note"><Icon name="flask" :size="19" /><strong>轻量 Demo · v0.1</strong><p>真实校验与计算，探索诊断流程。完整独立确认与回归重放尚未实现。</p></div><div class="local-footer"><span class="status-dot" :class="{ offline: !health }"></span>{{ health ? '本地服务已连接' : '本地服务未连接' }}<span>仅本机运行</span></div></div>
    </aside>
    <button v-if="mobileNav" class="nav-backdrop" aria-label="关闭导航" @click="mobileNav = false"></button>

    <div class="main-shell">
      <header class="topbar"><div class="breadcrumbs"><button class="icon-button mobile-menu" aria-label="打开导航" @click="mobileNav = !mobileNav"><Icon name="menu" /></button><span>工作空间</span><Icon name="chevron" :size="13" /><strong>升级检查</strong></div><div class="topbar-right"><span class="connection"><span class="status-dot" :class="{ offline: !health }"></span>{{ health ? '本地连接正常' : '服务连接中' }}</span><span class="topbar-divider"></span><span class="profile-avatar">本地</span></div></header>

      <main :aria-busy="loading || busy">
        <div class="page-heading" id="overview"><div><div class="eyebrow">MODEL REGRESSION ANALYSIS</div><h1>模型升级检查 <span class="pill">Demo</span></h1><p>看见总体指标背后的变化，让每一次升级都有证据。</p></div><div class="page-actions"><button class="button secondary" :disabled="busy || loading" @click="loadFixture()"><Icon :name="busy ? 'refresh' : 'flask'" :size="17" :class="{ spinning: busy }" />{{ busy ? '正在处理…' : '载入工程夹具' }}</button><button class="button primary" :disabled="busy || loading" @click="openImport"><Icon name="plus" :size="18" />导入预测对比</button></div></div>

        <div v-if="error" class="feedback error-feedback" role="alert"><Icon name="alert" :size="19" /><div><strong>操作未完成</strong><p>{{ error }}</p></div><button class="button small secondary" @click="initialize">重新连接</button><button class="icon-button" aria-label="关闭错误提示" @click="error = ''"><Icon name="close" :size="17" /></button></div>
        <div v-if="notice" class="feedback success-feedback" role="status"><Icon name="check" :size="18" /><span>{{ notice }}</span><button class="icon-button" aria-label="关闭操作提示" @click="notice = ''"><Icon name="close" :size="17" /></button></div>

        <div v-if="loading" class="loading-panel" role="status"><span class="loader"></span><strong>正在读取分析数据</strong><p>从本地服务载入已保存的分析与证据…</p></div>

        <template v-else-if="analysis && m">
          <div class="analysis-title"><div><span class="analysis-success"><span class="status-dot"></span>分析已完成</span><h2>{{ analysis.name }}<span :class="['source-badge', analysis.fixture_only ? 'fixture-badge' : 'import-badge']"><Icon :name="analysis.fixture_only ? 'flask' : 'upload'" :size="12" />{{ analysis.fixture_only ? '合成工程夹具' : '外部预测导入' }}</span></h2><div class="analysis-meta"><span><Icon name="clock" :size="13" />{{ date(analysis.created_at) }}</span><span>发现集 D · {{ m.n }} 条</span><span>标签 · {{ analysis.dataset.label_vocab.length }} 类</span><span class="mono">{{ shortHash(analysis.id) }}</span></div></div><div class="export-control"><button class="button secondary" :disabled="exporting" @click="exportOpen = !exportOpen" :aria-expanded="exportOpen"><Icon name="download" :size="16" />{{ exporting ? '正在导出…' : '导出报告' }}<Icon name="down" :size="14" /></button><div v-if="exportOpen" class="export-menu"><button @click="exportAnalysis('html')"><Icon name="file" :size="16" /><span>HTML 可读报告<small>适合审查与分享</small></span></button><button @click="exportAnalysis('json')"><Icon name="code" :size="16" /><span>JSON 结构化报告<small>保留计算结果与指纹</small></span></button></div></div></div>

          <div class="evidence-banner"><span class="evidence-icon"><Icon name="shield" :size="20" /></span><div><strong>仅描述：未达到可确认门禁</strong><p>当前仅分析发现集 D，确认集 C 未执行。证据不足，不能给出全面结论。{{ analysis.fixture_only ? '工程夹具用于验证软件流程，不是模型效果证据。' : '导入来源为外部声明，未独立验证模型身份与稳定性。' }}</p></div><span class="evidence-tag">DESCRIPTIVE ONLY</span></div>

          <section class="metric-grid" aria-label="发现集指标">
            <article class="metric-card"><div class="metric-header"><span>整体准确率变化</span><span class="metric-icon red"><Icon name="trend" :size="17" /></span></div><div :class="['metric-value', m.accuracy_drop != null && m.accuracy_drop > 0 ? 'text-red' : 'text-green']"><span v-if="m.accuracy_drop != null">{{ m.accuracy_drop > 0 ? '−' : m.accuracy_drop < 0 ? '+' : '' }}{{ Math.abs(m.accuracy_drop * 100).toFixed(1) }}<small>个百分点</small></span><span v-else class="metric-null">无可用分母</span></div><div class="metric-footer"><span>旧 {{ percent(m.old_accuracy) }}</span><Icon name="arrow" :size="13" /><strong>新 {{ percent(m.new_accuracy) }}</strong></div></article>
            <article class="metric-card"><div class="metric-header"><span>负向翻转</span><span class="metric-icon red"><Icon name="alert" :size="16" /></span></div><div class="metric-value">{{ m.b }}<small>条</small><span class="metric-rate red">{{ percent(m.negative_flip_rate) }}</span></div><div class="metric-footer"><span class="legend-dot negative"></span><span>旧版本正确 → 新版本错误</span></div></article>
            <article class="metric-card"><div class="metric-header"><span>正向翻转</span><span class="metric-icon green"><Icon name="spark" :size="17" /></span></div><div class="metric-value">{{ m.c }}<small>条</small><span class="metric-rate green">{{ percent(m.positive_flip_rate) }}</span></div><div class="metric-footer"><span class="legend-dot positive"></span><span>旧版本错误 → 新版本正确</span></div></article>
            <article class="metric-card"><div class="metric-header"><span>预测合法覆盖率</span><span class="metric-icon blue"><Icon name="check" :size="18" /></span></div><div class="metric-value">{{ percent(allCoverage, 0) }}<span class="check-label"><Icon name="check" :size="12" />已校验</span></div><div class="metric-footer"><span>D+C 共 {{ analysis.coverage.old.expected_count }} 对完整覆盖</span></div></article>
          </section>

          <div class="overview-grid">
            <section class="panel outcome-panel"><div class="panel-heading"><div><h3>成对预测变化</h3><p>同一发现集，四种结果，完整保留。</p></div><span class="pill muted">DISCOVERY</span></div><div class="paired-version"><div><span class="version-marker old">旧</span><strong>{{ analysis.old_model.name }}</strong></div><Icon name="arrow" :size="17" /><div><span class="version-marker new">新</span><strong>{{ analysis.new_model.name }}</strong></div></div><div class="outcome-bar" role="img" :aria-label="`双方正确 ${m.a} 条，旧对新错 ${m.b} 条，旧错新对 ${m.c} 条，双方错误 ${m.d} 条`"><div v-for="item in outcomes" :key="item.key" :class="item.cls" :style="{ width: `${m.n ? m[item.key] / m.n * 100 : 0}%` }" :title="`${item.name}：${m[item.key]} 条`"><span v-if="m.n && m[item.key] / m.n > 0.09">{{ m[item.key] }}</span></div></div><div class="outcome-legend"><button v-for="item in outcomes" :key="item.key" @click="outcome = item.value; loadCases(); go('cases')"><span :class="['legend-dot', item.cls]"></span><span>{{ item.name }}</span><strong>{{ m[item.key] }}</strong><small>{{ percent(m.n ? m[item.key] / m.n : null) }}</small></button></div><div class="panel-footnote"><Icon name="info" :size="14" /><span>负向、正向翻转率均以 D 全部 {{ m.n }} 条为分母。旧正确样本退化率为 {{ percent(m.old_correct_regression_rate) }}。</span></div></section>

            <section class="panel boundary-panel"><div class="panel-heading"><div><h3>本次分析的证据边界</h3><p>区分已计算结果与尚未验证的结论。</p></div><Icon name="shield" :size="19" /></div><div class="boundary-row"><span class="boundary-symbol complete"><Icon name="check" :size="14" /></span><div><strong>发现集 D</strong><p>{{ m.n }} 条已完成成对分析</p></div><span class="text-green">已执行</span></div><div class="boundary-row"><span class="boundary-symbol pending"><Icon name="clock" :size="14" /></span><div><strong>独立确认集 C</strong><p>{{ analysis.dataset.counts.CONFIRM || 0 }} 条保留，未用于当前指标</p></div><span class="muted-text">未执行</span></div><div class="boundary-row"><span class="boundary-symbol pending"><Icon name="clock" :size="14" /></span><div><strong>最终审计集 A</strong><p>{{ analysis.dataset.counts.AUDIT || 0 }} 条保留，不展示样本</p></div><span class="muted-text">未使用</span></div><div class="verdict"><span class="verdict-dot"></span><div><strong>证据不足，不能给出全面结论</strong><span>INCONCLUSIVE · 未进行独立确认</span></div></div></section>
          </div>

          <section class="panel section-space" id="groups"><div class="panel-heading"><div><h3><Icon name="layers" :size="18" />候选退化分组 <span class="count-neutral">{{ analysis.slices.length }}</span></h3><p>按可解释的表面特征定位变化。分组关联不代表退化根因。</p></div><div class="group-actions"><button class="text-button" :disabled="busy" @click="loadFixture('discovery')"><Icon name="flask" :size="13" />体验分组夹具</button><span class="pill muted">服务器固定排序</span></div></div><div v-if="analysis.slices.length" class="table-scroll"><table><caption class="sr-only">发现集候选分组，尚未独立确认</caption><thead><tr><th>分组条件</th><th>D 样本数</th><th>D 准确率下降</th><th>C 确认</th><th>统计状态</th></tr></thead><tbody><tr v-for="slice in analysis.slices" :key="slice.rank"><td><div class="predicate"><span class="rank">{{ String(slice.rank).padStart(2, '0') }}</span><span v-for="(condition, i) in slice.predicate.all" :key="i" class="feature-chip">{{ featureName(condition.feature) }} = {{ condition.value }}</span></div></td><td class="mono">{{ slice.discovery.n }}</td><td :class="{ 'text-red': (slice.discovery.accuracy_drop || 0) > 0 }">{{ points(slice.discovery.accuracy_drop) }}</td><td class="muted-text">未执行</td><td><span class="pill amber">发现集候选，尚未独立确认</span></td></tr></tbody></table></div><div v-else class="compact-empty"><span class="empty-icon"><Icon name="layers" :size="24" /></span><div><strong>当前没有满足条件的候选分组</strong><p>候选需满足 D 样本数 ≥ 30、负向翻转多于正向翻转、准确率下降 ≥ 5 个百分点。{{ analysis.fixture_only ? '12 条工程夹具不满足分组样本门槛。' : '可继续查看下方的逐条预测证据。' }}</p></div><span class="pill muted">未使用确认集</span></div></section>

          <section class="panel section-space confusion-panel"><div class="panel-heading"><div><h3><Icon name="chart" :size="18" />混淆变化</h3><p>按正确标签 → 预测标签，比较两版计数；计数不变的单元也保留。</p></div><span class="quiet-counter">{{ analysis.confusion_changes.total_nonzero }} 个混淆单元</span></div><div v-if="analysis.confusion_changes.cells.length" class="confusion-grid"><article v-for="(cell, index) in analysis.confusion_changes.cells.slice(0, 6)" :key="index" class="confusion-cell"><div><span class="label-token">{{ cell.gold_label }}</span><Icon name="arrow" :size="14" /><span class="label-token" :class="{ 'wrong-label': cell.gold_label !== cell.prediction_label }">{{ cell.prediction_label }}</span></div><p><span>旧 <strong>{{ cell.old_count }}</strong></span><Icon name="arrow" :size="14" /><span>新 <strong>{{ cell.new_count }}</strong></span><span :class="['delta', cell.delta > 0 ? 'delta-positive' : 'delta-negative']">{{ cell.delta > 0 ? '+' : '' }}{{ cell.delta }}</span></p></article></div><div v-else class="compact-empty"><Icon name="check" :size="23" /><div><strong>没有可展示的混淆单元</strong><p>当前发现集没有可用的混淆计数。</p></div></div><p v-if="analysis.confusion_changes.cells.length > 6 || analysis.confusion_changes.truncated" class="table-note">此处展示前 6 个混淆单元，更多结果请查看导出报告。计数增加或减少本身不等于好坏，须结合标签关系判断。</p></section>

          <section class="panel section-space cases-panel" id="cases" :aria-busy="casesLoading"><div class="panel-heading"><div><h3><Icon name="search" :size="18" />发现集证据 <span class="count-neutral">{{ m.n }}</span></h3><p>查看真实对齐样本。金标准保持原始标注，不提供人工修改。</p></div><span class="pill muted">仅 D 样本</span></div><div class="case-toolbar"><div class="filter-tabs" aria-label="按成对结果筛选"><button :class="{ selected: outcome === 'all' }" :aria-pressed="outcome === 'all'" @click="outcome = 'all'; loadCases()">全部<span>{{ m.n }}</span></button><button v-for="item in outcomes" :key="item.key" :class="{ selected: outcome === item.value }" :aria-pressed="outcome === item.value" @click="outcome = item.value; loadCases()"><span :class="['legend-dot', item.cls]"></span>{{ item.short }}<span>{{ m[item.key] }}</span></button></div></div><div v-if="caseError" class="inline-error" role="alert">{{ caseError }} <button class="text-button" @click="loadCases(cases.page)">重新加载</button></div><div v-else-if="casesLoading" class="case-loading" role="status"><span class="loader small-loader"></span>正在载入发现集证据…</div><div v-else-if="!cases.items.length" class="compact-empty"><Icon name="search" :size="26" /><div><strong>当前筛选下没有样本</strong><p>选择其他成对结果查看发现集证据。</p></div></div><div v-else class="table-scroll"><table class="cases-table"><caption class="sr-only">发现集文本、金标准与新旧预测对比</caption><thead><tr><th class="sample-heading">文本 / 样本 ID</th><th>正确标签</th><th>旧版本预测</th><th>新版本预测</th><th>成对结果</th></tr></thead><tbody><tr v-for="sample in cases.items" :key="sample.sample_id"><td class="sample-cell"><details class="sample-details"><summary><span>{{ sample.text }}</span></summary><div class="expanded-text">{{ sample.text }}</div><div class="sample-features"><span v-for="(value, key) in sample.features" :key="key" class="feature-chip">{{ featureName(String(key)) }}: {{ value }}</span></div></details><small class="sample-id mono">{{ sample.sample_id }}</small></td><td><span class="gold-token">{{ sample.gold_label }}</span></td><td><span :class="['prediction', sample.old_prediction_label === sample.gold_label ? 'correct' : 'incorrect']"><Icon :name="sample.old_prediction_label === sample.gold_label ? 'check' : 'close'" :size="12" />{{ sample.old_prediction_label }}</span></td><td><span :class="['prediction', sample.new_prediction_label === sample.gold_label ? 'correct' : 'incorrect']"><Icon :name="sample.new_prediction_label === sample.gold_label ? 'check' : 'close'" :size="12" />{{ sample.new_prediction_label }}</span></td><td><span :class="['outcome-tag', outcomeClass(sample.outcome)]">{{ outcomeName(sample.outcome) }}</span></td></tr></tbody></table></div><div class="pagination"><span>显示 {{ currentRows }} 条，共 {{ cases.total }} 条</span><div><span>{{ cases.page }} / {{ pages }}</span><button class="icon-button page-button previous" aria-label="上一页" :disabled="cases.page <= 1 || casesLoading" @click="loadCases(cases.page - 1)"><Icon name="chevron" :size="16" /></button><button class="icon-button page-button" aria-label="下一页" :disabled="cases.page >= pages || casesLoading" @click="loadCases(cases.page + 1)"><Icon name="chevron" :size="16" /></button></div></div></section>

          <section class="panel section-space" id="data"><div class="panel-heading"><div><h3><Icon name="database" :size="18" />数据与来源</h3><p>来源声明、分区和内容指纹随报告一起保存。</p></div><span class="pill purple">外部声明 · DECLARED</span></div><div class="data-grid"><div><h4>数据分区</h4><div class="partition-list"><div v-for="(label, key) in { TRAIN: '训练集', DEV: '开发集', DISCOVERY: '发现集 D', CONFIRM: '确认集 C', AUDIT: '审计集 A' }" :key="key" :class="{ emphasized: key === 'DISCOVERY' }"><span>{{ label }}</span><strong>{{ analysis.dataset.counts[key] || 0 }}</strong></div></div><p class="data-note">{{ analysis.dataset.row_count }} 行 · {{ analysis.dataset.component_count }} 个独立组件 · {{ analysis.dataset.label_vocab.length }} 个冻结标签</p></div><div class="source-detail"><h4>来源与预测</h4><dl><div><dt>来源</dt><dd>{{ analysis.fixture_only ? '合成工程夹具（非公开数据集实验）' : (analysis.dataset.source?.source_url || '外部导入，见报告来源声明') }}</dd></div><div><dt>版本 / 许可</dt><dd>{{ analysis.dataset.source?.version || '见导出报告' }} / {{ analysis.dataset.source?.license || '见导出报告' }}</dd></div><div><dt>旧预测</dt><dd>{{ analysis.coverage.old.legal_count }} / {{ analysis.coverage.old.expected_count }} 合法 <span class="muted-text">· 缺失 {{ analysis.coverage.old.missing_count }} · 非法 {{ analysis.coverage.old.invalid_count }} · 失败 {{ analysis.coverage.old.failed_count }}</span></dd></div><div><dt>新预测</dt><dd>{{ analysis.coverage.new.legal_count }} / {{ analysis.coverage.new.expected_count }} 合法 <span class="muted-text">· 缺失 {{ analysis.coverage.new.missing_count }} · 非法 {{ analysis.coverage.new.invalid_count }} · 失败 {{ analysis.coverage.new.failed_count }}</span></dd></div></dl></div><div class="fingerprints"><h4>内容指纹 <span>SHA-256</span></h4><div><span>数据集</span><code :title="analysis.dataset.content_sha256">{{ shortHash(analysis.dataset.content_sha256) }}</code></div><div><span>标签表</span><code :title="analysis.dataset.labelset_sha256">{{ shortHash(analysis.dataset.labelset_sha256) }}</code></div><div><span>候选家族</span><code :title="analysis.candidate_set_hash">{{ shortHash(analysis.candidate_set_hash) }}</code></div><div><span>分析结果</span><code :title="analysis.content_sha256">{{ shortHash(analysis.content_sha256) }}</code></div></div></div><details class="run-identifiers"><summary>查看模型运行标识 <Icon name="down" :size="14" /></summary><div><span>旧版本 run_id</span><code>{{ analysis.old_model.run_id }}</code><span class="pill purple">外部声明 · 身份未验证</span></div><div><span>新版本 run_id</span><code>{{ analysis.new_model.run_id }}</code><span class="pill purple">外部声明 · 身份未验证</span></div></details><div class="panel-footnote"><Icon name="info" :size="14" /><span>导入仅校验格式与内部一致性。模型身份、训练来源与权重真实性未获独立验证；内容指纹不等于权重指纹。</span></div><details class="limitations" v-if="analysis.limitations.length"><summary>查看本次分析的全部限制说明 <Icon name="down" :size="14" /></summary><ul><li v-for="(limitation, index) in analysis.limitations" :key="index">{{ limitation }}</li></ul></details></section>
        </template>

        <section v-else class="welcome-panel"><div class="welcome-visual" aria-hidden="true"><div class="welcome-orbit orbit-one"></div><div class="welcome-orbit orbit-two"></div><div class="floating-check"><Icon name="check" :size="18" /></div><div class="welcome-main-icon"><Icon name="chart" :size="43" /></div><div class="floating-data"><Icon name="layers" :size="18" /></div></div><span class="eyebrow">EVIDENCE BEFORE DECISIONS</span><h2>升级之后，哪些样本退步了？</h2><p>导入同一批样本的新旧预测，完整查看双向翻转、<br class="desktop-break" />混淆变化与逐条证据。所有指标均由本地后端计算。</p><div class="welcome-actions"><button class="button primary" :disabled="busy || !health" @click="openImport"><Icon name="upload" :size="17" />导入第一份预测对比</button><button class="button secondary" :disabled="busy || !health" @click="loadFixture()"><Icon name="flask" :size="17" />{{ busy ? '正在计算…' : '体验 12 条工程夹具' }}</button></div><div class="welcome-steps"><div><span>01</span><strong>严格校验</strong><p>完整预测 · 冻结标签 · 同一 scope</p></div><Icon name="chevron" :size="17" /><div><span>02</span><strong>发现变化</strong><p>双向翻转 · 候选分组 · D 证据</p></div><Icon name="chevron" :size="17" /><div><span>03</span><strong>留存报告</strong><p>真实指标 · 来源指纹 · 证据边界</p></div></div><p class="welcome-disclaimer"><Icon name="info" :size="14" />本 Demo 仅提供描述性分析，不包含独立确认、模型训练与回归重放。</p></section>

        <footer class="page-footer"><span><span class="footer-logo">R</span>RegressLab<span class="footer-separator">/</span>让模型变化可见，让诊断证据可追溯。</span><span>本地处理 · 发现集分析 · v0.1.0</span></footer>
      </main>
    </div>

    <dialog v-if="modalOpen" ref="modal" class="import-dialog" aria-labelledby="import-title" @cancel.prevent="closeImport" @click="(event) => { if (event.target === event.currentTarget) closeImport() }"><div class="dialog-content"><div class="dialog-heading"><div><span class="eyebrow">NEW ANALYSIS</span><h2 id="import-title">导入预测对比</h2><p>提交标注数据和两份完整预测，创建描述性分析。</p></div><button class="icon-button" :disabled="busy" aria-label="关闭导入窗口" @click="closeImport"><Icon name="close" /></button></div><form ref="importForm" @submit.prevent="submitImport"><div class="import-guidance"><Icon name="info" :size="18" /><p>单文件不超过 10 MB，数据最多 {{ health?.limits.max_rows || 5000 }} 行。预测必须完整覆盖 D+C 样本；缺失、非法标签或执行失败将拒绝整次分析。</p></div><div class="form-field"><label for="analysis-name">分析名称 <span>*</span></label><input id="analysis-name" v-model="form.name" name="name" required maxlength="100" placeholder="例如：意图分类 v1 → v2" autofocus :disabled="busy" /></div><div class="form-two-col"><div class="form-field"><label for="old-model">旧模型 / 应用版本 <span>*</span></label><input id="old-model" v-model="form.old_model_name" required maxlength="100" placeholder="intent-classifier-v1" :disabled="busy" /></div><div class="form-field"><label for="new-model">新模型 / 应用版本 <span>*</span></label><input id="new-model" v-model="form.new_model_name" required maxlength="100" placeholder="intent-classifier-v2" :disabled="busy" /></div></div><div class="form-field"><label for="parser-version">预测输出解析协议 <span>*</span></label><select id="parser-version" v-model="form.parser_version" :disabled="busy"><option value="label-json-v1">label-json-v1 · 原始输出为 {"label":"标签"}</option><option value="label-literal-v1">label-literal-v1 · 原始输出为精确标签文本</option></select><small>严格解析，不自动修复输出或映射标签。run_id 与 sample_id 来自预测文件。</small></div><div class="file-section-title"><h3>上传 JSONL 文件</h3><span>UTF-8 编码</span></div><div v-for="field in fileFields" :key="field.key" class="file-field"><label :for="field.key"><span class="file-icon"><Icon name="file" :size="20" /></span><span><strong>{{ field.title }} <span class="required-mark">*</span></strong><small>{{ field.hint }}</small></span></label><input :id="field.key" :name="field.key" type="file" accept=".jsonl,.ndjson,.json,application/json,application/x-ndjson" required :disabled="busy" @change="setFile(field.key, $event)" /></div><div class="example-links"><span>下载格式示例</span><a href="/examples/dataset.jsonl" download>标注数据 <Icon name="download" :size="12" /></a><a href="/examples/old-predictions.jsonl" download>旧预测 <Icon name="download" :size="12" /></a><a href="/examples/new-predictions.jsonl" download>新预测 <Icon name="download" :size="12" /></a></div><h3 class="form-subheading">数据来源声明</h3><div class="form-field"><label for="source-url">来源 URL <span>*</span></label><input id="source-url" v-model="form.source_url" required type="url" maxlength="2000" placeholder="https://example.org/dataset" :disabled="busy" /></div><div class="form-two-col"><div class="form-field"><label for="source-version">来源版本 <span>*</span></label><input id="source-version" v-model="form.source_version" required maxlength="100" placeholder="例如：1.1 或获取日期" :disabled="busy" /></div><div class="form-field"><label for="source-license">许可 <span>*</span></label><input id="source-license" v-model="form.license" required maxlength="300" placeholder="例如：CC-BY-4.0" :disabled="busy" /></div></div><div v-if="modalError" class="modal-error" role="alert"><strong><Icon name="alert" :size="17" />导入未完成</strong><p>{{ modalError }}</p><details v-if="modalErrorDetails" open><summary>校验详情</summary><pre>{{ modalErrorDetails }}</pre></details></div><div class="form-disclaimer"><Icon name="shield" :size="16" /><span>导入来源标记为 DECLARED，仅描述 D 结果；不执行独立确认，不证明模型身份或训练真实性。</span></div><div class="dialog-footer"><button class="button secondary" type="button" :disabled="busy" @click="closeImport">取消</button><button class="button primary" type="submit" :disabled="busy"><Icon :name="busy ? 'refresh' : 'upload'" :size="17" :class="{ spinning: busy }" />{{ busy ? '正在校验与计算…' : '校验并创建分析' }}</button></div></form></div></dialog>
  </div>
</template>
