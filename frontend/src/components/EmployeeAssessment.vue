<template>
  <section class="assessment-page">
    <div class="assessment-hero">
      <div>
        <p class="eyebrow">EMPLOYEE ASSESSMENT</p>
        <h1>员工考核一体化</h1>
        <p>同一套 Dify 工作流完成考核出题与员工答卷批阅。</p>
      </div>
      <div :class="['status-chip', status.configured ? 'ready' : 'warning']">
        <span></span>
        {{ status.configured ? 'Dify 已连接' : '尚未配置' }}
      </div>
    </div>

    <div class="mode-switch">
      <button :class="{ active: operation === '出题' }" @click="switchOperation('出题')">
        <b>01</b>
        <span><strong>智能出题</strong><small>结合知识库与历史错题生成 5 道简答题</small></span>
      </button>
      <button :class="{ active: operation === '批阅' }" @click="switchOperation('批阅')">
        <b>02</b>
        <span><strong>答卷批阅</strong><small>上传员工答卷，生成考核结果与改进建议</small></span>
      </button>
    </div>

    <el-alert
      v-if="!status.configured"
      type="warning"
      :closable="false"
      title="请先在 Dify 应用管理中配置 module_key=employee_assessment"
    />

    <div class="content-grid">
      <div class="form-panel">
        <div class="panel-title">
          <div>
            <h2>{{ operation === '出题' ? '生成考核题目' : '上传并批阅答卷' }}</h2>
            <p>{{ operation === '出题' ? '填写考核参数后，由工作流自动检索资料并命题。' : '答卷文件将上传至 Dify，由工作流提取内容并评分。' }}</p>
          </div>
          <el-button text :disabled="loading" @click="resetCurrent">重置</el-button>
        </div>

        <el-form label-position="top" class="assessment-form">
          <el-form-item label="考核员工ID" required>
            <el-input
              v-model="form.empId"
              maxlength="4"
              placeholder="请输入平台员工ID，例如：E002"
              autocapitalize="characters"
              @input="normalizeEmpIdInput"
            />
            <div class="field-tip">
              员工ID与平台工号、考核知识库保持一致，格式为 E 加三位数字，例如 E002。当前账号：
              {{ currentUser?.name || '未知' }}（{{ currentUser?.employee_id || currentUser?.username || '无工号' }}）。
            </div>
          </el-form-item>

          <el-form-item label="考核类型" required>
            <el-select v-model="form.assessmentType" style="width: 100%">
              <el-option label="员工入职考核" value="员工入职考核" />
              <el-option label="技能考核" value="技能考核" />
            </el-select>
          </el-form-item>

          <template v-if="operation === '出题'">
            <el-form-item label="难度级别">
              <el-select
                v-model="form.level"
                style="width: 100%"
                :disabled="form.assessmentType === '员工入职考核'"
              >
                <el-option
                  v-for="item in availableLevels"
                  :key="item"
                  :label="item"
                  :value="item"
                />
              </el-select>
              <div v-if="form.assessmentType === '员工入职考核'" class="field-tip">
                工作流规定入职考核统一使用普通难度。
              </div>
            </el-form-item>

            <el-form-item label="考核主题 / 补充要求">
              <el-input
                v-model="form.question"
                type="textarea"
                :rows="5"
                maxlength="500"
                show-word-limit
                placeholder="请输入考核主题或补充要求，例如：设备故障排查与客户交付；可不填写"
              />
            </el-form-item>

            <el-button
              class="primary-action"
              type="primary"
              size="large"
              :loading="loading"
              :disabled="!status.configured"
              @click="generateQuestions"
            >
              {{ loading ? '正在检索资料并生成题目…' : '开始生成考核题目' }}
            </el-button>
          </template>

          <template v-else>
            <el-form-item label="员工答卷" required>
              <el-upload
                ref="uploadRef"
                class="answer-uploader"
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
                <div class="upload-icon">A</div>
                <div class="el-upload__text">
                  将答卷拖到这里，或 <em>点击选择文件</em>
                </div>
                <template #tip>
                  <div class="el-upload__tip">支持 PDF、Word、TXT、Excel、CSV、PPT，单个文件不超过 30MB</div>
                </template>
              </el-upload>
            </el-form-item>

            <div v-if="selectedFile" class="file-summary">
              <div class="file-symbol">DOC</div>
              <div><strong>{{ selectedFile.name }}</strong><span>{{ formatSize(selectedFile.size) }}</span></div>
            </div>

            <el-button
              class="primary-action"
              type="primary"
              size="large"
              :loading="loading"
              :disabled="!status.configured || !selectedFile"
              @click="reviewAnswer"
            >
              {{ loading ? '正在提取答卷并严格批阅…' : '开始批阅员工答卷' }}
            </el-button>
          </template>
        </el-form>
      </div>

      <div class="guide-panel">
        <h3>工作流说明</h3>
        <div class="guide-item"><b>01</b><div><strong>出题依据</strong><p>复用员工历史错题，并检索外部企业知识库。</p></div></div>
        <div class="guide-item"><b>02</b><div><strong>题目结构</strong><p>当前工作流固定生成 5 道可评分的简答题。</p></div></div>
        <div class="guide-item"><b>03</b><div><strong>批阅结果</strong><p>工作流会评分、识别错题、生成个人改进建议并写入考核库。</p></div></div>
        <div class="identity-note">
          <span>当前操作人</span>
          <strong>{{ currentUser?.name || '当前用户' }}</strong>
          <small>{{ currentUser?.department_name || '未设置部门' }}</small>
        </div>
      </div>
    </div>

    <div v-if="generateResult" class="result-panel">
      <div class="result-header">
        <div>
          <p class="eyebrow">GENERATED QUESTIONS</p>
          <h2>考核题目</h2>
          <span>员工ID {{ generateResult.emp_id }} · {{ generateResult.assessment_type }} · {{ generateResult.level }}</span>
        </div>
        <el-button type="primary" plain @click="copyGeneratedQuestions">复制题目</el-button>
      </div>

      <ol v-if="generateResult.questions?.length" class="question-list">
        <li v-for="question in generateResult.questions" :key="question">{{ question }}</li>
      </ol>
      <pre v-else class="raw-result">{{ generateResult.raw_result }}</pre>
      <el-alert
        v-if="generateResult.question_count !== 5"
        type="warning"
        :closable="false"
        :title="`工作流本次解析到 ${generateResult.question_count || 0} 道题，请检查 Dify 运行结果。`"
      />
    </div>

    <div v-if="reviewResult" class="result-panel">
      <div class="result-header">
        <div>
          <p class="eyebrow">REVIEW RESULT</p>
          <h2>员工答卷批阅结果</h2>
          <span>{{ reviewResult.file_name }} · 员工ID {{ reviewResult.emp_id }}</span>
        </div>
        <el-button type="primary" plain @click="copyReviewResult">复制结果</el-button>
      </div>

      <template v-if="hasStructuredReview">
        <div class="review-cards">
          <div><span>考核结论</span><strong>{{ reviewResult.assessment.result || '未识别' }}</strong></div>
          <div><span>考核类型</span><strong>{{ reviewResult.assessment.assessment_type || reviewResult.assessment_type }}</strong></div>
          <div><span>考核日期</span><strong>{{ reviewResult.assessment.assessment_date || '未识别' }}</strong></div>
        </div>
        <div class="review-section">
          <span>错题 / 薄弱点</span>
          <p>{{ formatWrongQuestions(reviewResult.assessment.wrong_questions) }}</p>
        </div>
        <div class="review-section">
          <span>个人考试报告</span>
          <p>{{ reviewResult.assessment.result_analysis || '工作流未返回分析内容' }}</p>
        </div>
      </template>
      <pre v-else class="raw-result">{{ reviewResult.raw_result }}</pre>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  generateEmployeeAssessment,
  getEmployeeAssessmentStatus,
  reviewEmployeeAssessment
} from '../api/index.js'

const props = defineProps({
  initialOperation: { type: String, default: '出题' },
  currentUser: { type: Object, default: () => ({}) }
})

const operation = ref(props.initialOperation === '批阅' ? '批阅' : '出题')
const loading = ref(false)
const status = ref({ configured: false, message: '正在检查配置…' })
const uploadRef = ref()
const fileList = ref([])
const selectedFile = ref(null)
const generateResult = ref(null)
const reviewResult = ref(null)

const form = ref({
  empId: /^E\d{3}$/i.test(String(props.currentUser?.employee_id || '')) ? String(props.currentUser.employee_id).toUpperCase() : '',
  assessmentType: '员工入职考核',
  level: '普通',
  question: ''
})

const acceptTypes = '.pdf,.doc,.docx,.txt,.md,.rtf,.xls,.xlsx,.csv,.ppt,.pptx'
const availableLevels = computed(() => form.value.assessmentType === '员工入职考核'
  ? ['普通']
  : ['初级', '中级', '高级', '专家'])
const hasStructuredReview = computed(() => Object.keys(reviewResult.value?.assessment || {}).length > 0)

watch(() => form.value.assessmentType, (value) => {
  if (value === '员工入职考核') form.value.level = '普通'
  else if (form.value.level === '普通') form.value.level = '中级'
})

function normalizeEmpIdInput(value) {
  const raw = String(value || '').toUpperCase().replace(/[^E0-9]/g, '')
  const digits = raw.replace(/\D/g, '').slice(0, 3)
  if (digits) {
    form.value.empId = `E${digits}`
  } else {
    form.value.empId = raw.includes('E') ? 'E' : ''
  }
}

function validateBaseForm() {
  form.value.empId = String(form.value.empId || '').trim().toUpperCase()
  if (!/^E\d{3}$/.test(form.value.empId)) {
    ElMessage.warning('员工ID格式应为 E 加三位数字，例如 E002')
    return false
  }
  if (!form.value.assessmentType) {
    ElMessage.warning('请选择考核类型')
    return false
  }
  return true
}

function switchOperation(value) {
  if (loading.value) return
  operation.value = value
  generateResult.value = null
  reviewResult.value = null
}

async function loadStatus() {
  try {
    const response = await getEmployeeAssessmentStatus()
    status.value = response.data
  } catch (error) {
    status.value = { configured: false, message: error.response?.data?.detail || error.message }
  }
}

async function generateQuestions() {
  if (!validateBaseForm()) return
  loading.value = true
  generateResult.value = null
  try {
    const response = await generateEmployeeAssessment({
      emp_id: form.value.empId,
      assessment_type: form.value.assessmentType,
      level: form.value.level,
      question: form.value.question.trim()
    })
    generateResult.value = response.data
    ElMessage.success('考核题目生成完成')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '考核题目生成失败')
  } finally {
    loading.value = false
  }
}

async function reviewAnswer() {
  if (!validateBaseForm()) return
  if (!selectedFile.value) {
    ElMessage.warning('请先选择员工答卷文件')
    return
  }

  loading.value = true
  reviewResult.value = null
  try {
    const data = new FormData()
    data.append('emp_id', form.value.empId)
    data.append('assessment_type', form.value.assessmentType)
    data.append('file', selectedFile.value)
    const response = await reviewEmployeeAssessment(data)
    reviewResult.value = response.data
    ElMessage.success('员工答卷批阅完成')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '员工答卷批阅失败')
  } finally {
    loading.value = false
  }
}

function handleFileChange(uploadFile, files) {
  const raw = uploadFile.raw
  if (!raw) return
  if (raw.size > 30 * 1024 * 1024) {
    ElMessage.error('答卷文件不能超过30MB')
    uploadRef.value?.clearFiles()
    selectedFile.value = null
    fileList.value = []
    return
  }
  selectedFile.value = raw
  fileList.value = files.slice(-1)
  reviewResult.value = null
}

function handleRemove() {
  selectedFile.value = null
  fileList.value = []
}

function handleExceed(files) {
  uploadRef.value?.clearFiles()
  uploadRef.value?.handleStart(files[0])
}

function formatSize(size = 0) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatWrongQuestions(value) {
  if (Array.isArray(value)) return value.length ? value.join('；') : '无错题'
  if (value && typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value || '无错题')
}

async function copyGeneratedQuestions() {
  const text = generateResult.value?.questions?.length
    ? generateResult.value.questions.map((item, index) => `${index + 1}. ${item}`).join('\n')
    : generateResult.value?.raw_result || ''
  await copyText(text, '题目已复制')
}

async function copyReviewResult() {
  const item = reviewResult.value
  const assessment = item?.assessment || {}
  const text = Object.keys(assessment).length
    ? [
        `员工ID：${assessment.emp_id || item.emp_id || ''}`,
        `考核类型：${assessment.assessment_type || item.assessment_type || ''}`,
        `考核结果：${assessment.result || ''}`,
        `考核日期：${assessment.assessment_date || ''}`,
        `错题：${formatWrongQuestions(assessment.wrong_questions)}`,
        `分析：${assessment.result_analysis || ''}`
      ].join('\n')
    : item?.raw_result || ''
  await copyText(text, '批阅结果已复制')
}

async function copyText(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(successMessage)
  } catch {
    ElMessage.error('复制失败，请手动选择内容复制')
  }
}

function resetCurrent() {
  if (operation.value === '出题') {
    form.value.question = ''
    generateResult.value = null
  } else {
    uploadRef.value?.clearFiles()
    selectedFile.value = null
    fileList.value = []
    reviewResult.value = null
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.assessment-page { display: flex; flex-direction: column; gap: 22px; }
.assessment-hero {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;
  padding: 30px 32px; border: 1px solid rgba(110,139,255,.18); border-radius: 24px;
  background: radial-gradient(circle at 82% 20%, rgba(82,188,255,.2), transparent 28%), linear-gradient(135deg, rgba(24,33,67,.97), rgba(12,17,38,.98));
}
.eyebrow { margin: 0 0 8px; color: #8ea7ff; font-size: 12px; font-weight: 700; letter-spacing: 2px; }
.assessment-hero h1, .result-header h2 { margin: 0; color: #f4f7ff; }
.assessment-hero > div > p:last-child { margin: 12px 0 0; color: #9aa7c3; }
.status-chip { display: inline-flex; align-items: center; gap: 8px; padding: 9px 13px; border-radius: 999px; font-size: 13px; }
.status-chip span { width: 8px; height: 8px; border-radius: 50%; }
.status-chip.ready { color: #74e6ba; background: rgba(53,190,137,.12); }
.status-chip.ready span { background: #52d7a6; }
.status-chip.warning { color: #ffcd78; background: rgba(255,183,64,.12); }
.status-chip.warning span { background: #ffb740; }
.mode-switch { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 14px; }
.mode-switch button {
  display: flex; align-items: center; gap: 14px; padding: 17px 20px; text-align: left; cursor: pointer;
  border: 1px solid rgba(110,139,255,.14); border-radius: 18px; color: #b4bfd8; background: rgba(15,22,48,.72);
}
.mode-switch button.active { border-color: rgba(112,135,255,.65); color: #fff; background: linear-gradient(135deg, rgba(74,102,220,.28), rgba(99,71,201,.22)); }
.mode-switch b { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 12px; color: #9daeff; background: rgba(101,124,255,.16); }
.mode-switch span { display: flex; flex-direction: column; gap: 4px; }
.mode-switch strong { color: inherit; font-size: 15px; }
.mode-switch small { color: #7f8da9; }
.content-grid { display: grid; grid-template-columns: minmax(0,1fr) 320px; gap: 22px; }
.form-panel, .guide-panel, .result-panel { border: 1px solid rgba(110,139,255,.14); border-radius: 22px; background: rgba(15,22,48,.9); box-shadow: 0 18px 50px rgba(2,8,25,.18); }
.form-panel, .guide-panel { padding: 24px; }
.panel-title, .result-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.panel-title h2, .guide-panel h3 { margin: 0; color: #edf2ff; }
.panel-title p { margin: 7px 0 0; color: #7f8da9; }
.assessment-form { margin-top: 22px; }
.assessment-form :deep(.el-form-item__label) { color: #c8d2e8; }
.field-tip { margin-top: 7px; color: #6f7d99; font-size: 12px; line-height: 1.55; }
.primary-action { width: 100%; margin-top: 4px; }
.answer-uploader { width: 100%; }
.answer-uploader :deep(.el-upload), .answer-uploader :deep(.el-upload-dragger) { width: 100%; }
.answer-uploader :deep(.el-upload-dragger) { border: 1px dashed rgba(120,146,255,.42); border-radius: 18px; background: rgba(24,34,69,.55); padding: 34px 20px; }
.upload-icon { width: 50px; height: 50px; margin: 0 auto 14px; display: grid; place-items: center; border-radius: 16px; color: #fff; font-weight: 800; background: linear-gradient(135deg,#637dff,#8d5cff); }
.file-summary { display: flex; align-items: center; gap: 12px; margin: 0 0 16px; padding: 13px 15px; border-radius: 15px; background: rgba(89,112,219,.1); }
.file-symbol { width: 42px; height: 38px; display: grid; place-items: center; border-radius: 11px; background: rgba(107,126,255,.2); color: #aebdff; font-size: 10px; font-weight: 800; }
.file-summary > div:last-child { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.file-summary strong { overflow: hidden; color: #e9efff; text-overflow: ellipsis; white-space: nowrap; }
.file-summary span { color: #7786a4; font-size: 12px; }
.guide-panel { display: flex; flex-direction: column; gap: 18px; }
.guide-item { display: flex; gap: 12px; }
.guide-item b { flex: 0 0 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; color: #91a6ff; background: rgba(91,115,226,.14); }
.guide-item strong { color: #dfe7fa; }
.guide-item p { margin: 5px 0 0; color: #7887a3; font-size: 13px; line-height: 1.6; }
.identity-note { margin-top: auto; padding: 16px; border-radius: 15px; background: rgba(82,105,206,.1); }
.identity-note span, .identity-note small { display: block; color: #7887a3; font-size: 12px; }
.identity-note strong { display: block; margin: 6px 0 3px; color: #eef3ff; }
.result-panel { padding: 26px; }
.result-header span { display: block; margin-top: 8px; color: #7f8da9; font-size: 13px; }
.question-list { display: grid; gap: 12px; margin: 22px 0 0; padding: 0; list-style: none; counter-reset: question; }
.question-list li { position: relative; padding: 17px 18px 17px 58px; border: 1px solid rgba(111,139,246,.12); border-radius: 16px; color: #dfe7f8; background: rgba(24,34,69,.42); line-height: 1.7; counter-increment: question; }
.question-list li::before { content: counter(question); position: absolute; left: 17px; top: 15px; width: 27px; height: 27px; display: grid; place-items: center; border-radius: 9px; color: #aebcff; background: rgba(102,124,255,.16); font-weight: 800; }
.review-cards { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px; margin-top: 22px; }
.review-cards div { padding: 17px; border-radius: 16px; background: rgba(32,44,84,.55); }
.review-cards span, .review-section span { display: block; color: #7f8da9; font-size: 12px; }
.review-cards strong { display: block; margin-top: 8px; color: #eef3ff; }
.review-section { margin-top: 14px; padding: 18px; border-radius: 16px; background: rgba(24,34,69,.42); }
.review-section p { margin: 8px 0 0; color: #d6dff3; line-height: 1.75; white-space: pre-wrap; }
.raw-result { margin: 22px 0 0; padding: 18px; overflow: auto; border-radius: 16px; color: #d6dff3; background: rgba(8,13,30,.65); white-space: pre-wrap; word-break: break-word; }
@media (max-width: 980px) { .content-grid { grid-template-columns: 1fr; } .review-cards { grid-template-columns: 1fr; } }
@media (max-width: 680px) { .assessment-hero, .result-header { flex-direction: column; } .mode-switch { grid-template-columns: 1fr; } }
</style>
