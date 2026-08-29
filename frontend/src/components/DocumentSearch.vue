<template>
  <section class="knowledge-page">
    <header class="knowledge-topbar">
      <div class="model-name">
        <span class="model-mark">S</span>
        <div><strong>SmartOffice 知识助手</strong><small>企业内部文档检索</small></div>
      </div>
      <div :class="['service-state', { ready: configured }]">
        <i></i>{{ statusText }}
      </div>
    </header>

    <main :class="['knowledge-main', { answered: hasConversation }]">
      <div v-if="!hasConversation" class="empty-home">
        <div class="home-logo">S</div>
        <h1>今天想查询什么内部资料？</h1>
        <p>制度、流程、报销标准、行政规范和业务文档，都可以直接提问。</p>

        <div class="composer home-composer">
          <el-input
            v-model="question"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            maxlength="2000"
            resize="none"
            placeholder="请输入要查询的内部制度或流程，例如：出差住宿标准是什么？"
            :disabled="loading"
            @keydown.enter.exact.prevent="submitSearch"
          />
          <button class="send-button" :disabled="loading || question.trim().length < 2" @click="submitSearch">
            <span v-if="!loading">↑</span>
            <i v-else></i>
          </button>
        </div>
        <div class="composer-hint">Enter 发送，Shift + Enter 换行</div>

        <div class="suggestions">
          <button v-for="item in examples" :key="item" @click="useExample(item)">
            <span>⌕</span>{{ item }}
          </button>
        </div>
      </div>

      <div v-else class="conversation-wrap">
        <div class="conversation-head">
          <div><strong>内部文档检索</strong><small>{{ workflowName }}</small></div>
          <button @click="newConversation">新建查询</button>
        </div>

        <div class="conversation-body">
          <div class="message user-message">
            <div class="message-label">我</div>
            <div class="user-bubble">{{ lastQuestion }}</div>
          </div>

          <div class="message assistant-message">
            <div class="assistant-avatar">S</div>
            <div class="assistant-content">
              <div class="assistant-title">知识助手</div>
              <div v-if="loading" class="thinking-line">
                <span>正在检索企业知识库并整理答案</span><i></i><i></i><i></i>
              </div>
              <div v-else class="answer-text">{{ answer }}</div>
              <button v-if="answer && !loading" class="copy-button" @click="copyAnswer">复制答案</button>
            </div>
          </div>
        </div>

        <div class="bottom-composer-wrap">
          <div class="composer bottom-composer">
            <el-input
              v-model="question"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 4 }"
              maxlength="2000"
              resize="none"
              placeholder="继续查询内部文档，例如：请补充适用范围和审批流程"
              :disabled="loading"
              @keydown.enter.exact.prevent="submitSearch"
            />
            <button class="send-button" :disabled="loading || question.trim().length < 2" @click="submitSearch">
              <span v-if="!loading">↑</span>
              <i v-else></i>
            </button>
          </div>
          <small>答案来自已接入的企业知识库，请结合最新制度文件核对。</small>
        </div>
      </div>
    </main>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getDocumentSearchStatus, searchDocuments } from '../api'

const question = ref('')
const lastQuestion = ref('')
const answer = ref('')
const workflowName = ref('文档检索')
const loading = ref(false)
const configured = ref(false)
const statusText = ref('正在检查配置')
const hasConversation = computed(() => Boolean(lastQuestion.value || loading.value || answer.value))

const examples = [
  '员工请年假需要走什么流程？',
  '出差机票和酒店的报销标准是什么？',
  '办公室设备损坏后如何报修？',
  '公司的核心价值观和行为准则是什么？'
]

async function loadStatus() {
  try {
    const response = await getDocumentSearchStatus()
    configured.value = Boolean(response.data.configured)
    statusText.value = response.data.message || (configured.value ? '知识库可用' : '尚未配置')
    workflowName.value = response.data.workflow_name || '文档检索'
  } catch {
    configured.value = false
    statusText.value = '配置检查失败'
  }
}

function useExample(text) {
  question.value = text
}

function newConversation() {
  question.value = ''
  lastQuestion.value = ''
  answer.value = ''
}

async function submitSearch() {
  const text = question.value.trim()
  if (text.length < 2 || loading.value) return ElMessage.warning('请输入要检索的问题')

  lastQuestion.value = text
  question.value = ''
  answer.value = ''
  loading.value = true
  try {
    const response = await searchDocuments({ question: text })
    answer.value = response.data.answer || '未检索到与该问题相关的内容。'
    workflowName.value = response.data.workflow_name || workflowName.value
    configured.value = true
    statusText.value = '知识库可用'
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || '文档检索失败'
    answer.value = `检索失败：${typeof detail === 'string' ? detail : '请稍后重试'}`
    ElMessage.error(typeof detail === 'string' ? detail : '文档检索失败')
  } finally {
    loading.value = false
  }
}

async function copyAnswer() {
  try {
    await navigator.clipboard.writeText(answer.value)
    ElMessage.success('检索结果已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.knowledge-page {
  min-height: calc(100vh - 104px);
  overflow: hidden;
  border: 1px solid #e5e7eb;
  border-radius: 20px;
  background: #fff;
  color: #111827;
  box-shadow: 0 16px 50px rgba(2, 6, 23, .18);
}
.knowledge-topbar { display: flex; align-items: center; justify-content: space-between; padding: 18px 24px; border-bottom: 1px solid #eef0f4; }
.model-name { display: flex; align-items: center; gap: 11px; }
.model-name div { display: flex; flex-direction: column; gap: 2px; }
.model-name strong { color: #111827; font-size: 15px; }
.model-name small { color: #9ca3af; }
.model-mark { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 11px; background: linear-gradient(135deg, #4f46e5, #7c3aed); color: white; font-weight: 800; }
.service-state { display: inline-flex; align-items: center; gap: 7px; padding: 7px 11px; border-radius: 999px; background: #f3f4f6; color: #6b7280; font-size: 12px; }
.service-state i { width: 7px; height: 7px; border-radius: 50%; background: #9ca3af; }
.service-state.ready { background: #ecfdf5; color: #047857; }
.service-state.ready i { background: #10b981; box-shadow: 0 0 8px rgba(16,185,129,.55); }
.knowledge-main { min-height: calc(100vh - 176px); }
.empty-home { display: flex; flex-direction: column; align-items: center; justify-content: center; width: min(920px, calc(100% - 40px)); min-height: calc(100vh - 200px); margin: 0 auto; text-align: center; }
.home-logo { display: grid; place-items: center; width: 58px; height: 58px; margin-bottom: 20px; border-radius: 18px; background: #111827; color: white; font-size: 25px; font-weight: 800; box-shadow: 0 12px 28px rgba(17,24,39,.18); }
.empty-home h1 { margin: 0; color: #111827; font-size: clamp(30px, 4vw, 46px); letter-spacing: -.03em; }
.empty-home > p { margin: 13px 0 30px; color: #6b7280; font-size: 16px; }
.composer { display: flex; align-items: flex-end; gap: 10px; padding: 10px 11px 10px 20px; border: 1px solid #e5e7eb; border-radius: 28px; background: #f7f8fb; box-shadow: 0 8px 30px rgba(15, 23, 42, .08); transition: .2s ease; }
.composer:focus-within { border-color: #a5b4fc; background: #fff; box-shadow: 0 10px 34px rgba(79,70,229,.13); }
.home-composer { width: min(880px, 100%); }
.composer :deep(.el-textarea__inner) { min-height: 34px !important; padding: 7px 2px; border: none; background: transparent; box-shadow: none !important; color: #111827; font-size: 15px; line-height: 1.55; }
.composer :deep(.el-textarea__inner::placeholder) { color: #9ca3af; }
.send-button { display: grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; border: 0; border-radius: 50%; background: #4f46e5; color: white; cursor: pointer; font-size: 22px; font-weight: 700; transition: .18s ease; }
.send-button:hover:not(:disabled) { transform: translateY(-1px); background: #4338ca; }
.send-button:disabled { background: #c7cbd4; cursor: not-allowed; }
.send-button i { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,.4); border-top-color: #fff; border-radius: 50%; animation: search-spin .8s linear infinite; }
.composer-hint { margin-top: 9px; color: #9ca3af; font-size: 12px; }
.suggestions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; width: min(760px, 100%); margin-top: 28px; }
.suggestions button { display: flex; align-items: center; gap: 9px; padding: 12px 15px; border: 1px solid #e5e7eb; border-radius: 13px; background: #fff; color: #4b5563; cursor: pointer; text-align: left; }
.suggestions button:hover { border-color: #c7d2fe; background: #f8faff; color: #3730a3; }
.suggestions span { color: #6366f1; }
.conversation-wrap { display: flex; flex-direction: column; min-height: calc(100vh - 176px); }
.conversation-head { display: flex; align-items: center; justify-content: space-between; padding: 18px max(24px, calc((100% - 900px) / 2)); border-bottom: 1px solid #f0f1f4; }
.conversation-head div { display: flex; flex-direction: column; gap: 2px; }
.conversation-head strong { color: #111827; }
.conversation-head small { color: #9ca3af; }
.conversation-head button, .copy-button { border: 0; background: transparent; color: #4f46e5; cursor: pointer; }
.conversation-body { flex: 1; width: min(900px, calc(100% - 40px)); margin: 0 auto; padding: 34px 0 150px; }
.message { display: flex; gap: 13px; margin-bottom: 28px; }
.user-message { justify-content: flex-end; align-items: flex-start; }
.message-label { display: none; }
.user-bubble {
  max-width: 76%;
  padding: 13px 17px;
  border-radius: 18px 18px 5px 18px;
  background: #eef2ff;
  color: #1e293b !important;
  -webkit-text-fill-color: #1e293b !important;
  opacity: 1;
  line-height: 1.7;
  font-weight: 500;
  text-shadow: none;
}
.assistant-avatar { display: grid; place-items: center; flex: 0 0 34px; width: 34px; height: 34px; border-radius: 11px; background: #111827; color: #fff; font-weight: 800; }
.assistant-content { flex: 1; min-width: 0; padding-top: 3px; }
.assistant-title { margin-bottom: 8px; color: #111827; font-weight: 700; }
.answer-text { color: #334155; line-height: 1.9; white-space: pre-wrap; word-break: break-word; }
.copy-button { margin-top: 15px; padding: 0; }
.thinking-line { display: flex; align-items: center; gap: 5px; color: #64748b; }
.thinking-line span { margin-right: 4px; }
.thinking-line i { width: 6px; height: 6px; border-radius: 50%; background: #6366f1; animation: thinking-dot 1.2s infinite ease-in-out; }
.thinking-line i:nth-child(2) { animation-delay: .15s; }
.thinking-line i:nth-child(3) { animation-delay: .3s; }
.thinking-line i:nth-child(4) { animation-delay: .45s; }
.bottom-composer-wrap { position: sticky; bottom: 0; width: min(940px, calc(100% - 32px)); margin: -120px auto 0; padding: 34px 20px 18px; background: linear-gradient(to bottom, rgba(255,255,255,0), #fff 34%); }
.bottom-composer { width: 100%; box-sizing: border-box; }
.bottom-composer-wrap > small { display: block; margin-top: 8px; color: #9ca3af; text-align: center; }
@keyframes search-spin { to { transform: rotate(360deg); } }
@keyframes thinking-dot { 0%, 70%, 100% { opacity: .3; transform: translateY(0); } 35% { opacity: 1; transform: translateY(-4px); } }
@media (max-width: 720px) { .knowledge-page { border-radius: 14px; } .knowledge-topbar { padding: 14px 16px; } .empty-home { width: calc(100% - 24px); } .empty-home h1 { font-size: 30px; } .suggestions { grid-template-columns: 1fr; } .conversation-body { width: calc(100% - 24px); } .user-bubble { max-width: 88%; } .service-state { max-width: 130px; overflow: hidden; white-space: nowrap; } }

/* 主题级最终覆盖：避免全局 .user-bubble 白字规则覆盖本组件 */
:global(:root[data-theme='light']) .knowledge-page .user-message .user-bubble,
:global(:root[data-theme='light']) .knowledge-page .user-message .user-bubble * {
  background: #eef2ff !important;
  color: #1e293b !important;
  -webkit-text-fill-color: #1e293b !important;
  border-color: #c7d2fe !important;
  opacity: 1 !important;
  text-shadow: none !important;
}

:global(:root[data-theme='dark']) .knowledge-page .user-message .user-bubble,
:global(:root[data-theme='dark']) .knowledge-page .user-message .user-bubble * {
  background: linear-gradient(135deg, #334a91, #493c88) !important;
  color: #f8fafc !important;
  -webkit-text-fill-color: #f8fafc !important;
  border-color: rgba(129, 140, 248, .42) !important;
  opacity: 1 !important;
  text-shadow: none !important;
}

</style>
