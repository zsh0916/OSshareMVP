<template>
  <section class="report-page">
    <div class="report-hero">
      <div>
        <p class="eyebrow">DAILY REPORT ASSISTANT</p>
        <h1>日报与阶段报表</h1>
        <p>提交个人日报，或按时间、人员和项目查询日报汇总、周报、月报与阶段报表。</p>
      </div>

      <div :class="['status-chip', status.configured ? 'ready' : 'warning']">
        <span></span>
        {{ status.configured ? 'Dify 已连接' : '尚未配置' }}
      </div>
    </div>

    <el-alert
      v-if="!status.configured"
      type="warning"
      :closable="false"
      title="请在 Dify 应用管理中配置 module_key=report_generate"
      class="config-alert"
    />

    <div class="report-grid">
      <el-card class="composer-card" shadow="never">
        <template #header>
          <div class="card-heading">
            <div>
              <strong>工作日报助手</strong>
              <small>提交或查询完成后，结果将在独立弹窗中展示</small>
            </div>

            <div class="header-actions">
              <el-button
                v-if="result"
                text
                type="primary"
                :disabled="loading"
                @click="openLatestResult"
              >
                查看最近结果
              </el-button>
              <el-button text :disabled="loading" @click="newConversation">
                新会话
              </el-button>
            </div>
          </div>
        </template>

        <div class="mode-cards">
          <button
            type="button"
            :class="{ active: mode === 'submit' }"
            :disabled="loading"
            @click="selectMode('submit')"
          >
            <b>日报提交</b>
            <span>描述已完成工作、后续计划、风险与协调事项</span>
          </button>

          <button
            type="button"
            :class="{ active: mode === 'query' }"
            :disabled="loading"
            @click="selectMode('query')"
          >
            <b>报表查询</b>
            <span>按日期、人员或项目生成日报汇总与阶段报表</span>
          </button>
        </div>

        <el-form label-position="top">
          <el-form-item label="当前员工 / 查询人员">
            <el-input
              v-model="receiverName"
              maxlength="100"
              :disabled="loading"
              placeholder="不填写则使用当前登录员工"
            />
          </el-form-item>

          <el-form-item
            :label="mode === 'submit' ? '今天做了什么' : '需要查询什么报表'"
            required
          >
            <el-input
              v-model="query"
              type="textarea"
              :rows="7"
              maxlength="3000"
              show-word-limit
              :placeholder="placeholder"
              :disabled="loading"
              @keydown.ctrl.enter.prevent="sendMessage"
            />
            <div class="field-tip">按 Ctrl + Enter 可直接提交。</div>
          </el-form-item>

          <div class="quick-row">
            <span>示例：</span>
            <button
              v-for="item in examples"
              :key="item"
              type="button"
              :disabled="loading"
              @click="query = item"
            >
              {{ item }}
            </button>
          </div>

          <el-button
            type="primary"
            size="large"
            class="main-action"
            :loading="loading"
            :disabled="!status.configured || loading"
            @click="sendMessage"
          >
            {{
              loading
                ? '工作流正在处理，请稍候…'
                : mode === 'submit'
                  ? '整理并提交日报'
                  : '生成汇总报表'
            }}
          </el-button>
        </el-form>
      </el-card>

      <el-card class="guide-card" shadow="never">
        <template #header>
          <strong>使用说明</strong>
        </template>

        <div class="guide-item">
          <b>01</b>
          <div>
            <strong>日报提交</strong>
            <p>Dify 会整理日报字段，并通过数据库插件写入 daily_report。</p>
          </div>
        </div>

        <div class="guide-item">
          <b>02</b>
          <div>
            <strong>报表查询</strong>
            <p>支持今天、昨天、最近 7 天、本周、上周、本月及自定义日期。</p>
          </div>
        </div>

        <div class="guide-item">
          <b>03</b>
          <div>
            <strong>查询维度</strong>
            <p>可在问题中加入员工姓名、工号、项目、客户或事项关键词。</p>
          </div>
        </div>

        <div class="guide-item">
          <b>04</b>
          <div>
            <strong>结果展示</strong>
            <p>完整结果统一在弹窗中排版，当前页面不再向下展开长文本。</p>
          </div>
        </div>
      </el-card>
    </div>

    <el-dialog
      v-model="resultDialogVisible"
      :title="dialogTitle"
      width="980px"
      top="5vh"
      class="report-result-dialog"
      append-to-body
      destroy-on-close
      :close-on-click-modal="false"
    >
      <div v-if="result" class="report-result-shell">
        <div class="dialog-result-header">
          <div>
            <p class="dialog-eyebrow">GENERATED REPORT</p>
            <h2>{{ dialogTitle }}</h2>
            <span>
              {{ result.receiverName || currentUser?.name || '当前用户' }}
              ·
              {{ result.workflowName || '日报与阶段报表工作流' }}
            </span>
          </div>

          <div class="result-badge">
            {{ result.mode === 'submit' ? '日报提交' : '报表查询' }}
          </div>
        </div>

        <div class="report-query-box">
          <span>本次输入</span>
          <p>{{ result.query }}</p>
        </div>

        <article
          class="report-markdown"
          v-html="renderedResult"
        ></article>
      </div>

      <template #footer>
        <el-button @click="resultDialogVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!result?.answer"
          @click="copyText(result?.answer || '')"
        >
          复制完整结果
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { renderSafeMarkdown } from '../utils/markdown.js'
import {
  chatReportGenerate,
  getReportGenerateStatus
} from '../api/index.js'

const props = defineProps({
  currentUser: {
    type: Object,
    default: () => ({})
  }
})

const status = ref({
  configured: false,
  message: '正在检查配置…'
})
const mode = ref('submit')
const query = ref('')
const receiverName = ref('')
const conversationId = ref('')
const loading = ref(false)
const result = ref(null)
const resultDialogVisible = ref(false)

const submitExamples = [
  '今天完成了客户需求梳理和接口联调，明天继续做回归测试，目前需要产品确认两个字段。',
  '昨天完成设备巡检和故障处理，无重大风险，明天安排备件盘点。'
]

const queryExamples = [
  '查询王芳近三天的报表',
  '汇总最近7天所有人的日报',
  '生成上周技术部项目交付相关的工作汇总'
]

const examples = computed(() => (
  mode.value === 'submit' ? submitExamples : queryExamples
))

const placeholder = computed(() => (
  mode.value === 'submit'
    ? '请输入今天的工作内容，例如：今天完成客户需求梳理，明天继续联调，目前需要产品确认两个字段。'
    : '请输入报表查询要求，例如：查询王芳近三天的日报，并汇总已完成工作、风险和待协调事项。'
))

const dialogTitle = computed(() => (
  result.value?.mode === 'submit'
    ? '日报提交结果'
    : '日报与阶段报表'
))

function normalizeMarkdown(value) {
  return String(value || '')
    .replace(/\r\n?/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/^\s*[“"]|[”"]\s*$/g, '')
    .replace(/^[ \t]+(?=#{1,6}\s*)/gm, '')
    .replace(/^＃+/gm, (value) => '#'.repeat(value.length))
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

const renderedResult = computed(() => (
  renderSafeMarkdown(normalizeMarkdown(result.value?.answer || ''))
))

watch(
  () => props.currentUser?.name,
  (name) => {
    if (!receiverName.value) {
      receiverName.value = String(name || '')
    }
  },
  { immediate: true }
)

function selectMode(value) {
  mode.value = value
  query.value = ''
}

function openLatestResult() {
  if (!result.value) {
    ElMessage.info('暂无可查看的结果')
    return
  }
  resultDialogVisible.value = true
}

function newConversation() {
  conversationId.value = ''
  result.value = null
  resultDialogVisible.value = false
  query.value = ''
  ElMessage.success('已开始新会话')
}

async function loadStatus() {
  try {
    const response = await getReportGenerateStatus()
    status.value = response.data
  } catch (error) {
    console.error(error)
    status.value = {
      configured: false,
      message: error?.response?.data?.detail || '配置状态检查失败'
    }
  }
}

async function sendMessage() {
  const content = String(query.value || '').trim()

  if (!content) {
    ElMessage.warning('请输入日报内容或报表查询条件')
    return
  }

  loading.value = true

  try {
    const response = await chatReportGenerate({
      query: content,
      receiver_name: receiverName.value || props.currentUser?.name || '',
      conversation_id: conversationId.value
    })

    conversationId.value = response.data.conversation_id || ''

    result.value = {
      answer: response.data.answer || '',
      query: content,
      mode: mode.value,
      receiverName: receiverName.value || props.currentUser?.name || '',
      workflowName: response.data.workflow_name || ''
    }

    query.value = ''
    resultDialogVisible.value = true

    if (response.data.restarted) {
      ElMessage.info('原 Dify 会话已失效，系统已自动建立新会话')
    }

    ElMessage.success(
      mode.value === 'submit'
        ? '日报处理完成'
        : '报表生成完成'
    )
  } catch (error) {
    console.error(error)
    ElMessage.error(
      error?.response?.data?.detail
      || error?.message
      || '日报工作流调用失败'
    )
  } finally {
    loading.value = false
  }
}

async function copyText(text) {
  const content = String(text || '')
  if (!content) {
    ElMessage.warning('暂无可复制内容')
    return
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(content)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = content
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    ElMessage.success('完整结果已复制')
  } catch (error) {
    console.error(error)
    ElMessage.error('复制失败，请手动选择文本')
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.report-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 4px;
}

.report-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 30px;
  border: 1px solid rgba(101, 123, 255, .18);
  border-radius: 20px;
  color: #fff;
  background:
    radial-gradient(circle at 84% 18%, rgba(81, 225, 218, .22), transparent 28%),
    linear-gradient(135deg, #102a43, #087f8c);
}

.report-hero h1 {
  margin: 4px 0 8px;
  color: #fff;
  font-size: 30px;
  line-height: 1.25;
}

.report-hero > div > p:last-child {
  margin: 0;
  color: #d5eff2;
  line-height: 1.65;
}

.eyebrow {
  margin: 0;
  color: #8de4ee;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 1.5px;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  padding: 8px 13px;
  border-radius: 999px;
  background: rgba(255, 255, 255, .12);
  white-space: nowrap;
}

.status-chip span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f79009;
}

.status-chip.ready span {
  background: #32d583;
}

.config-alert {
  margin: 0;
}

.report-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(290px, .75fr);
  gap: 18px;
}

.composer-card,
.guide-card {
  border-radius: 16px;
}

.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.card-heading > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-heading strong {
  font-size: 18px;
}

.card-heading small,
.field-tip {
  color: var(--text-muted, #667085);
  font-size: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.mode-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 20px;
}

.mode-cards button {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  padding: 15px;
  border: 1px solid var(--border, #d0d5dd);
  border-radius: 12px;
  color: var(--text, #101828);
  background: var(--surface, #fff);
  text-align: left;
  cursor: pointer;
  transition: border-color .18s ease, background .18s ease, transform .18s ease;
}

.mode-cards button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.mode-cards button.active {
  border-color: #0e9384;
  background: color-mix(in srgb, #0e9384 9%, var(--surface, #fff));
  box-shadow: 0 0 0 2px rgba(14, 147, 132, .08);
}

.mode-cards button:disabled {
  cursor: not-allowed;
  opacity: .65;
}

.mode-cards b {
  color: inherit;
}

.mode-cards span {
  color: var(--text-muted, #667085);
  font-size: 12px;
  line-height: 1.5;
}

.quick-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: -4px 0 16px;
  color: var(--text-muted, #667085);
  font-size: 12px;
}

.quick-row button {
  padding: 5px 10px;
  border: 1px solid var(--border, #d0d5dd);
  border-radius: 999px;
  color: var(--text-secondary, #475467);
  background: var(--surface, #fff);
  cursor: pointer;
}

.quick-row button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.main-action {
  width: 100%;
  min-height: 42px;
}

.guide-item {
  display: flex;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border-soft, #eaecf0);
}

.guide-item:last-child {
  border-bottom: 0;
}

.guide-item > b {
  display: grid;
  place-items: center;
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  color: #027a48;
  background: #ecfdf3;
}

.guide-item strong {
  color: var(--text, #101828);
  font-size: 14px;
}

.guide-item p {
  margin: 5px 0 0;
  color: var(--text-muted, #667085);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 960px) {
  .report-grid {
    grid-template-columns: 1fr;
  }

  .report-hero {
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .card-heading,
  .dialog-result-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .mode-cards {
    grid-template-columns: 1fr;
  }

  .header-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>

<style>
.report-result-dialog.el-dialog {
  max-width: calc(100vw - 28px);
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 30px 95px rgba(15, 23, 42, .34);
}

.report-result-dialog .el-dialog__header {
  margin: 0;
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
}

.report-result-dialog .el-dialog__title {
  color: #111827;
  font-size: 20px;
  font-weight: 750;
}

.report-result-dialog .el-dialog__headerbtn {
  top: 12px;
}

.report-result-dialog .el-dialog__body {
  padding: 0;
}

.report-result-dialog .el-dialog__footer {
  padding: 14px 24px 18px;
  border-top: 1px solid #e5e7eb;
}

.report-result-shell {
  max-height: 75vh;
  overflow-y: auto;
  padding: 22px 26px 30px;
  background: #f8fafc;
}

.dialog-result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
  padding: 20px 22px;
  border: 1px solid #dbe4f0;
  border-radius: 16px;
  background: linear-gradient(135deg, #fff, #f1f5f9);
}

.dialog-eyebrow {
  margin: 0 0 6px;
  color: #0f766e;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1.6px;
}

.dialog-result-header h2 {
  margin: 0;
  color: #0f172a;
  font-size: 24px;
  line-height: 1.3;
}

.dialog-result-header span {
  display: block;
  margin-top: 8px;
  color: #64748b;
  font-size: 13px;
}

.result-badge {
  flex: 0 0 auto;
  padding: 7px 12px;
  border-radius: 999px;
  color: #115e59;
  background: #ccfbf1;
  font-size: 13px;
  font-weight: 750;
}

.report-query-box {
  margin-bottom: 16px;
  padding: 13px 15px;
  border-left: 4px solid #14b8a6;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 5px 18px rgba(15, 23, 42, .04);
}

.report-query-box span {
  color: #64748b;
  font-size: 12px;
}

.report-query-box p {
  margin: 5px 0 0;
  color: #334155;
  line-height: 1.65;
}

.report-markdown {
  padding: 28px 32px;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  color: #334155;
  background: #fff;
  word-break: break-word;
  box-shadow: 0 8px 28px rgba(15, 23, 42, .05);
}

.report-markdown h1,
.report-markdown h2,
.report-markdown h3,
.report-markdown h4 {
  color: #0f172a;
  font-weight: 760;
  line-height: 1.38;
}

.report-markdown h1 {
  margin: 0 0 22px;
  padding-bottom: 12px;
  border-bottom: 2px solid #0f766e;
  font-size: 27px;
}

.report-markdown h2 {
  margin: 28px 0 13px;
  padding-left: 11px;
  border-left: 4px solid #14b8a6;
  font-size: 22px;
}

.report-markdown h3 {
  margin: 23px 0 11px;
  color: #1e293b;
  font-size: 18px;
}

.report-markdown h4 {
  margin: 19px 0 9px;
  color: #334155;
  font-size: 16px;
}

.report-markdown h1:first-child,
.report-markdown h2:first-child,
.report-markdown h3:first-child {
  margin-top: 0;
}

.report-markdown p {
  margin: 9px 0;
  color: #334155;
  font-size: 15px;
  line-height: 1.85;
}

.report-markdown strong {
  color: #0f172a;
  font-weight: 750;
}

.report-markdown em {
  color: #475569;
}

.report-markdown ul,
.report-markdown ol {
  margin: 10px 0 16px;
  padding-left: 26px;
}

.report-markdown li {
  margin: 7px 0;
  padding-left: 2px;
  color: #334155;
  line-height: 1.75;
}

.report-markdown li::marker {
  color: #0f766e;
  font-weight: 700;
}

.report-markdown blockquote {
  margin: 16px 0;
  padding: 12px 15px;
  border-left: 4px solid #38bdf8;
  border-radius: 0 9px 9px 0;
  color: #334155;
  background: #f0f9ff;
}

.report-markdown code {
  padding: 2px 6px;
  border-radius: 5px;
  color: #be123c;
  background: #fff1f2;
  font-family: Consolas, Monaco, monospace;
  font-size: .92em;
}

.report-markdown hr {
  margin: 24px 0;
  border: 0;
  border-top: 1px solid #dbe4f0;
}

.report-markdown a {
  color: #2563eb;
  text-decoration: none;
}

.report-markdown a:hover {
  text-decoration: underline;
}

.report-markdown .markdown-table-wrap {
  overflow-x: auto;
  margin: 17px 0;
  border: 1px solid #dbe4f0;
  border-radius: 10px;
}

.report-markdown table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
}

.report-markdown th,
.report-markdown td {
  padding: 11px 13px;
  border-right: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
  color: #334155;
  text-align: left;
  vertical-align: top;
}

.report-markdown th:last-child,
.report-markdown td:last-child {
  border-right: 0;
}

.report-markdown tr:last-child td {
  border-bottom: 0;
}

.report-markdown th {
  color: #0f172a;
  background: #f1f5f9;
  font-weight: 750;
}

.report-markdown .task-list {
  padding-left: 0;
  list-style: none;
}

.report-markdown .task-list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.report-markdown .task-check {
  display: inline-grid;
  place-items: center;
  flex: 0 0 17px;
  width: 17px;
  height: 17px;
  margin-top: 4px;
  border: 1px solid #94a3b8;
  border-radius: 4px;
}

.report-markdown .task-check.checked {
  border-color: #10b981;
  color: #fff;
  background: #10b981;
}

.report-markdown .markdown-empty {
  color: #64748b;
  text-align: center;
}

/* append-to-body 后仍保持暗色主题可读性 */
:root[data-theme='dark'] .report-result-dialog.el-dialog {
  border-color: #273551;
  background: #101827;
}

:root[data-theme='dark'] .report-result-dialog .el-dialog__header,
:root[data-theme='dark'] .report-result-dialog .el-dialog__footer {
  border-color: #273551;
  background: #101827;
}

:root[data-theme='dark'] .report-result-dialog .el-dialog__title {
  color: #f8fafc;
}

:root[data-theme='dark'] .report-result-shell {
  background: #0b1220;
}

:root[data-theme='dark'] .dialog-result-header {
  border-color: #2a3a58;
  background: linear-gradient(135deg, #182338, #111a2b);
}

:root[data-theme='dark'] .dialog-result-header h2 {
  color: #f8fafc;
}

:root[data-theme='dark'] .dialog-result-header span {
  color: #94a3b8;
}

:root[data-theme='dark'] .report-query-box,
:root[data-theme='dark'] .report-markdown {
  border-color: #273551;
  background: #111a2b;
  box-shadow: none;
}

:root[data-theme='dark'] .report-query-box p,
:root[data-theme='dark'] .report-markdown p,
:root[data-theme='dark'] .report-markdown li,
:root[data-theme='dark'] .report-markdown td {
  color: #d7e0ef;
}

:root[data-theme='dark'] .report-markdown h1,
:root[data-theme='dark'] .report-markdown h2,
:root[data-theme='dark'] .report-markdown h3,
:root[data-theme='dark'] .report-markdown h4,
:root[data-theme='dark'] .report-markdown strong,
:root[data-theme='dark'] .report-markdown th {
  color: #f8fafc;
}

:root[data-theme='dark'] .report-markdown th {
  background: #182338;
}

:root[data-theme='dark'] .report-markdown th,
:root[data-theme='dark'] .report-markdown td,
:root[data-theme='dark'] .report-markdown .markdown-table-wrap {
  border-color: #2a3a58;
}

:root[data-theme='dark'] .report-markdown blockquote {
  color: #d7e0ef;
  background: #10233b;
}

@media (max-width: 640px) {
  .report-result-shell {
    padding: 15px;
  }

  .report-markdown {
    padding: 20px 18px;
  }
}
</style>
