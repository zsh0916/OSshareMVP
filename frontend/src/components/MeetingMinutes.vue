<template>
  <section class="meeting-page">
    <div class="meeting-hero">
      <div>
        <p class="eyebrow">AI MEETING ASSISTANT</p>
        <h1>智能会议纪要</h1>
        <p>上传会议录音或视频，自动生成转写文本、正式会议纪要和结构化会议信息。</p>
      </div>
      <div :class="['status-chip', status.configured ? 'ready' : 'warning']">
        <span></span>
        {{ status.configured ? 'Dify 已连接' : '尚未配置' }}
      </div>
    </div>

    <div class="meeting-grid">
      <div class="upload-panel">
        <div class="panel-title">
          <div>
            <h2>上传会议文件</h2>
            <p>支持音频和视频，单个文件不超过 100MB。</p>
          </div>
          <el-button text @click="resetAll" :disabled="loading">清空</el-button>
        </div>

        <el-upload
          ref="uploadRef"
          class="meeting-uploader"
          drag
          action="#"
          :auto-upload="false"
          :limit="1"
          :file-list="fileList"
          :accept="acceptTypes"
          :on-change="handleFileChange"
          :on-remove="handleRemove"
          :on-exceed="handleExceed"
        >
          <div class="upload-icon">♫</div>
          <div class="el-upload__text">
            将会议文件拖到这里，或 <em>点击选择</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              mp3 / wav / m4a / aac / flac / ogg / wma / amr / mp4 / mov
            </div>
          </template>
        </el-upload>

        <div v-if="selectedFile" class="file-summary">
          <div class="file-symbol">M</div>
          <div>
            <strong>{{ selectedFile.name }}</strong>
            <span>{{ formatSize(selectedFile.size) }}</span>
          </div>
        </div>

        <el-button
          class="generate-button"
          type="primary"
          size="large"
          :loading="loading"
          :disabled="!selectedFile || !status.configured"
          @click="generate"
        >
          {{ loading ? '正在转写并生成纪要，请稍候…' : '开始生成会议纪要' }}
        </el-button>

        <el-alert
          v-if="!status.configured"
          type="warning"
          :closable="false"
          title="请先在 Dify 应用管理中配置 module_key=meeting_minutes"
        />
      </div>

      <div class="guide-panel">
        <h3>使用建议</h3>
        <div class="guide-item">
          <b>01</b>
          <div><strong>录音清晰</strong><p>尽量减少环境噪声，避免多人同时说话。</p></div>
        </div>
        <div class="guide-item">
          <b>02</b>
          <div><strong>内容完整</strong><p>会议中明确主题、结论、负责人和截止时间。</p></div>
        </div>
        <div class="guide-item">
          <b>03</b>
          <div><strong>等待完成</strong><p>较长文件需要数分钟，请勿在生成过程中刷新页面。</p></div>
        </div>
      </div>
    </div>

    <div v-if="result" class="result-ready-bar">
      <div>
        <span class="ready-icon">✓</span>
        <div>
          <strong>会议纪要已生成</strong>
          <small>{{ result.structured_info?.topic || result.file_name || '会议文件' }}</small>
        </div>
      </div>
      <el-button type="primary" @click="resultDialogVisible = true">查看完整纪要</el-button>
    </div>

    <el-dialog
      v-model="resultDialogVisible"
      title="智能会议纪要"
      width="980px"
      class="meeting-result-dialog"
      append-to-body
      destroy-on-close
    >
      <div v-if="result" class="meeting-result-shell">
        <div class="dialog-result-header">
          <div>
            <p class="dialog-eyebrow">GENERATED RESULT</p>
            <h2>{{ result.structured_info?.topic || '会议纪要生成结果' }}</h2>
            <span>{{ result.file_name }} · {{ result.generated_at || '刚刚生成' }}</span>
          </div>
          <el-button type="primary" plain @click="copyMinutes">复制会议纪要</el-button>
        </div>

        <div v-if="structuredItems.length" class="dialog-info-cards">
          <div v-for="item in structuredItems" :key="item.key" class="dialog-info-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value || '未识别' }}</strong>
          </div>
        </div>

        <el-tabs v-model="activeTab" class="dialog-result-tabs">
          <el-tab-pane label="标准会议纪要" name="minutes">
            <article class="meeting-markdown" v-html="renderedMinutes"></article>
          </el-tab-pane>
          <el-tab-pane label="结构化信息" name="structured">
            <div class="dialog-structured-list">
              <div v-for="item in allStructuredItems" :key="item.key">
                <span>{{ item.label }}</span>
                <p>{{ item.value || '未识别' }}</p>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="清洗后转写" name="cleaned">
            <div class="dialog-transcript-text">{{ result.cleaned_transcript || '无清洗后转写内容' }}</div>
          </el-tab-pane>
          <el-tab-pane label="原始转写" name="transcript">
            <div class="dialog-transcript-text">{{ result.transcript || '无原始转写内容' }}</div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button @click="resultDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="copyMinutes">复制会议纪要</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { renderSafeMarkdown } from '../utils/markdown.js'
import {
  generateMeetingMinutes,
  getMeetingMinutesStatus
} from '../api/index.js'

const uploadRef = ref()
const fileList = ref([])
const selectedFile = ref(null)
const loading = ref(false)
const result = ref(null)
const activeTab = ref('minutes')
const resultDialogVisible = ref(false)
const status = ref({ configured: false, message: '正在检查配置…' })

const acceptTypes = '.mp3,.wav,.m4a,.aac,.flac,.ogg,.wma,.amr,.mp4,.mov'

const labels = {
  department: '所属部门',
  meeting_time: '会议时间',
  duration: '会议时长（分钟）',
  topic: '会议主题',
  attendees: '参会人员',
  meeting_goal: '会议目标',
  meeting_result: '会议结果',
  decisions: '决议事项',
  action_items: '行动项',
  keywords: '关键词',
  summary: '核心摘要',
  missing_fields: '待确认信息',
  confidence: '识别置信度'
}

const structuredItems = computed(() => {
  const info = result.value?.structured_info || {}
  return ['department', 'meeting_time', 'duration', 'attendees', 'confidence']
    .filter(key => info[key] !== undefined)
    .map(key => ({ key, label: labels[key] || key, value: String(info[key] ?? '') }))
})

const allStructuredItems = computed(() => {
  const info = result.value?.structured_info || {}
  return Object.entries(info).map(([key, value]) => ({
    key,
    label: labels[key] || key,
    value: typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '')
  }))
})

const renderedMinutes = computed(() => renderSafeMarkdown(result.value?.meeting_minutes || ''))

function formatSize(size = 0) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function handleFileChange(uploadFile, files) {
  const raw = uploadFile.raw
  if (!raw) return

  if (raw.size > 100 * 1024 * 1024) {
    ElMessage.error('文件不能超过 100MB')
    fileList.value = []
    selectedFile.value = null
    return
  }

  selectedFile.value = raw
  fileList.value = files.slice(-1)
  result.value = null
}

function handleRemove() {
  selectedFile.value = null
  fileList.value = []
}

function handleExceed(files) {
  uploadRef.value?.clearFiles()
  const raw = files[0]
  uploadRef.value?.handleStart(raw)
}

async function loadStatus() {
  try {
    const response = await getMeetingMinutesStatus()
    status.value = response.data
  } catch (error) {
    status.value = {
      configured: false,
      message: error.response?.data?.detail || error.message
    }
  }
}

async function generate() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择会议录音或视频')
    return
  }

  loading.value = true
  result.value = null
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    const response = await generateMeetingMinutes(formData)
    result.value = response.data
    activeTab.value = 'minutes'
    resultDialogVisible.value = true
    ElMessage.success('会议纪要生成完成')
  } catch (error) {
    ElMessage.error(
      error.response?.data?.detail
      || error.message
      || '会议纪要生成失败'
    )
  } finally {
    loading.value = false
  }
}

async function copyMinutes() {
  try {
    await navigator.clipboard.writeText(result.value?.meeting_minutes || '')
    ElMessage.success('会议纪要已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

function resetAll() {
  uploadRef.value?.clearFiles()
  selectedFile.value = null
  fileList.value = []
  result.value = null
  activeTab.value = 'minutes'
  resultDialogVisible.value = false
}

onMounted(loadStatus)
</script>

<style scoped>
.meeting-page {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.meeting-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 30px 32px;
  border: 1px solid rgba(110, 139, 255, .18);
  border-radius: 24px;
  background:
    radial-gradient(circle at 82% 20%, rgba(102, 92, 255, .22), transparent 28%),
    linear-gradient(135deg, rgba(24, 33, 67, .97), rgba(12, 17, 38, .98));
}

.eyebrow {
  margin: 0 0 8px;
  color: #8ea7ff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 2px;
}

.meeting-hero h1,
.result-header h2 {
  margin: 0;
  color: #f4f7ff;
}

.meeting-hero > div > p:last-child {
  margin: 12px 0 0;
  color: #9aa7c3;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 13px;
  border-radius: 999px;
  font-size: 13px;
}

.status-chip span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-chip.ready {
  color: #74e6ba;
  background: rgba(53, 190, 137, .12);
}

.status-chip.ready span { background: #52d7a6; }
.status-chip.warning {
  color: #ffcd78;
  background: rgba(255, 183, 64, .12);
}
.status-chip.warning span { background: #ffb740; }

.meeting-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 22px;
}

.upload-panel,
.guide-panel,
.result-panel {
  border: 1px solid rgba(110, 139, 255, .14);
  border-radius: 22px;
  background: rgba(15, 22, 48, .9);
  box-shadow: 0 18px 50px rgba(2, 8, 25, .18);
}

.upload-panel { padding: 24px; }
.guide-panel { padding: 24px; }

.panel-title,
.result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.panel-title h2,
.guide-panel h3 {
  margin: 0;
  color: #edf2ff;
}

.panel-title p {
  margin: 7px 0 0;
  color: #7f8da9;
}

.meeting-uploader {
  margin: 22px 0 14px;
}

.meeting-uploader :deep(.el-upload-dragger) {
  border: 1px dashed rgba(120, 146, 255, .42);
  border-radius: 18px;
  background: rgba(24, 34, 69, .55);
  padding: 38px 20px;
}

.upload-icon {
  width: 54px;
  height: 54px;
  margin: 0 auto 14px;
  display: grid;
  place-items: center;
  border-radius: 17px;
  color: #fff;
  font-size: 25px;
  background: linear-gradient(135deg, #637dff, #8d5cff);
}

.file-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 14px 0;
  padding: 13px 15px;
  border-radius: 15px;
  background: rgba(89, 112, 219, .1);
}

.file-symbol {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: rgba(107, 126, 255, .2);
  color: #aebdff;
  font-weight: 800;
}

.file-summary div:last-child {
  display: flex;
  flex-direction: column;
}

.file-summary strong { color: #eaf0ff; }
.file-summary span { color: #7f8da9; font-size: 12px; margin-top: 3px; }

.generate-button {
  width: 100%;
  margin: 8px 0 16px;
  min-height: 46px;
}

.guide-item {
  display: flex;
  gap: 13px;
  padding: 18px 0;
  border-bottom: 1px solid rgba(126, 148, 215, .1);
}

.guide-item:last-child { border-bottom: 0; }
.guide-item b { color: #6f89ff; }
.guide-item strong { color: #e9efff; }
.guide-item p { margin: 5px 0 0; color: #8491aa; line-height: 1.6; font-size: 13px; }

.result-panel { padding: 26px; }
.result-header span { display: block; margin-top: 8px; color: #7f8da9; font-size: 13px; }

.info-cards {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin: 24px 0 12px;
}

.info-card {
  min-height: 80px;
  padding: 14px;
  border-radius: 15px;
  background: rgba(40, 53, 99, .48);
}

.info-card span {
  display: block;
  color: #7f8da9;
  font-size: 12px;
  margin-bottom: 8px;
}

.info-card strong {
  color: #e8eeff;
  font-size: 14px;
  line-height: 1.45;
}

.result-tabs {
  margin-top: 18px;
}

.result-text {
  min-height: 240px;
  max-height: 640px;
  overflow: auto;
  margin: 0;
  padding: 20px;
  white-space: pre-wrap;
  word-break: break-word;
  border-radius: 16px;
  color: #dce5ff;
  background: rgba(7, 12, 29, .76);
  font-family: inherit;
  line-height: 1.8;
}

.structured-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.structured-list > div {
  padding: 15px;
  border-radius: 14px;
  background: rgba(35, 47, 90, .48);
}

.structured-list span {
  color: #8291af;
  font-size: 12px;
}

.structured-list p {
  margin: 7px 0 0;
  color: #e2e9ff;
  white-space: pre-wrap;
  line-height: 1.6;
}

@media (max-width: 1100px) {
  .meeting-grid { grid-template-columns: 1fr; }
  .info-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 700px) {
  .meeting-hero,
  .result-header { flex-direction: column; }
  .info-cards,
  .structured-list { grid-template-columns: 1fr; }
}

.result-ready-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 20px;
  border: 1px solid rgba(82, 215, 166, .26);
  border-radius: 18px;
  background: rgba(17, 94, 89, .18);
}
.result-ready-bar > div { display: flex; align-items: center; gap: 12px; min-width: 0; }
.result-ready-bar > div > div { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.result-ready-bar strong { color: #ecfdf5; }
.result-ready-bar small { overflow: hidden; color: #a7f3d0; text-overflow: ellipsis; white-space: nowrap; }
.ready-icon { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 50%; background: #10b981; color: #fff; font-weight: 800; }
</style>

<style>
.meeting-result-dialog.el-dialog { overflow: hidden; border-radius: 20px; background: #fff; box-shadow: 0 30px 95px rgba(15, 23, 42, .34); }
.meeting-result-dialog .el-dialog__header { margin: 0; padding: 20px 24px; border-bottom: 1px solid #e5e7eb; }
.meeting-result-dialog .el-dialog__title { color: #111827; font-size: 20px; font-weight: 750; }
.meeting-result-dialog .el-dialog__body { padding: 0; }
.meeting-result-dialog .el-dialog__footer { padding: 14px 24px 18px; border-top: 1px solid #e5e7eb; }
.meeting-result-shell { max-height: 76vh; overflow-y: auto; padding: 22px 26px 30px; background: #f8fafc; }
.dialog-result-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 20px 22px; border-radius: 14px; background: linear-gradient(135deg, #eff6ff, #eef2ff); }
.dialog-result-header h2 { margin: 3px 0 7px; color: #0f172a; font-size: 23px; }
.dialog-result-header span { color: #64748b; font-size: 13px; }
.dialog-eyebrow { margin: 0; color: #4f46e5; font-size: 11px; font-weight: 750; letter-spacing: 1.6px; }
.dialog-info-cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }
.dialog-info-card { display: flex; flex-direction: column; gap: 5px; padding: 12px 13px; border: 1px solid #dbeafe; border-radius: 10px; background: #fff; }
.dialog-info-card span { color: #64748b; font-size: 12px; }
.dialog-info-card strong { color: #0f172a; font-size: 13px; word-break: break-word; }
.dialog-result-tabs { margin-top: 8px; }
.meeting-markdown { min-height: 220px; padding: 24px 28px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; color: #24324a; font-size: 15px; line-height: 1.85; }
.meeting-markdown h2, .meeting-markdown h3, .meeting-markdown h4 { margin: 24px 0 10px; color: #0f172a; line-height: 1.35; }
.meeting-markdown h2:first-child, .meeting-markdown h3:first-child, .meeting-markdown h4:first-child { margin-top: 0; }
.meeting-markdown h2 { padding-bottom: 9px; border-bottom: 1px solid #dbeafe; font-size: 22px; }
.meeting-markdown h3 { padding-left: 10px; border-left: 4px solid #6366f1; font-size: 18px; }
.meeting-markdown h4 { font-size: 16px; }
.meeting-markdown p { margin: 8px 0; }
.meeting-markdown ul, .meeting-markdown ol { margin: 8px 0 12px; padding-left: 25px; }
.meeting-markdown li { margin: 5px 0; }
.meeting-markdown strong { color: #111827; font-weight: 750; }
.meeting-markdown code { padding: 2px 6px; border-radius: 5px; background: #eef2ff; color: #4338ca; font-family: Consolas, monospace; }
.meeting-markdown blockquote { margin: 12px 0; padding: 10px 14px; border-left: 4px solid #a5b4fc; background: #eef2ff; color: #3730a3; }
.meeting-markdown hr { margin: 20px 0; border: 0; border-top: 1px solid #dbeafe; }
.meeting-markdown .markdown-table-wrap { overflow-x: auto; margin: 14px 0; }
.meeting-markdown table { width: 100%; border-collapse: collapse; }
.meeting-markdown th, .meeting-markdown td { padding: 9px 11px; border: 1px solid #dbeafe; text-align: left; }
.meeting-markdown th { background: #eef2ff; color: #3730a3; }
.meeting-markdown .task-list { padding-left: 0; list-style: none; }
.meeting-markdown .task-check { display: inline-grid; place-items: center; width: 17px; height: 17px; margin-right: 8px; border: 1px solid #94a3b8; border-radius: 4px; color: #fff; font-size: 12px; }
.meeting-markdown .task-check.checked { border-color: #10b981; background: #10b981; }
.dialog-structured-list { display: grid; gap: 10px; }
.dialog-structured-list > div { padding: 13px 15px; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; }
.dialog-structured-list span { color: #64748b; font-size: 12px; }
.dialog-structured-list p { margin: 5px 0 0; color: #24324a; line-height: 1.7; white-space: pre-wrap; }
.dialog-transcript-text { min-height: 220px; padding: 20px 22px; border: 1px solid #e2e8f0; border-radius: 12px; background: #fff; color: #334155; line-height: 1.8; white-space: pre-wrap; word-break: break-word; }
@media (max-width: 900px) { .meeting-result-dialog.el-dialog { width: 95% !important; } .dialog-info-cards { grid-template-columns: repeat(2, 1fr); } .meeting-result-shell { padding: 16px; } .meeting-markdown { padding: 18px; } }
</style>
