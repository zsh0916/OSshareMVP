import axios from 'axios'

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000`

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: Number(import.meta.env.VITE_API_TIMEOUT || 360000)
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('smart_office_access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('smart-office-unauthorized'))
    }
    const responseData = error.response?.data || {}
    if (
      error.response?.status === 403 &&
      (
        responseData.code === 'PASSWORD_CHANGE_REQUIRED' ||
        String(responseData.detail || '').includes('修改初始密码')
      )
    ) {
      window.dispatchEvent(new CustomEvent('smart-office-password-change-required'))
    }
    return Promise.reject(error)
  }
)

export default api

// 账号与个人信息
export function loginAccount(data) { return api.post('/api/auth/login', data) }
export function logoutAccount() { return api.post('/api/auth/logout') }
export function getCurrentUser() {
  return api.get('/api/auth/me', { timeout: 10000 })
}
export function changePassword(data) { return api.post('/api/auth/change-password', data) }
export function getWorkbenchSummary() { return api.get('/api/workbench/summary') }
export function getTaskSummary() { return api.get('/api/tasks/summary') }
export function getTasks(params) { return api.get('/api/tasks', { params }) }

// 通知中心
export function getNotifications(params) { return api.get('/api/notifications', { params }) }
export function markNotificationRead(id) { return api.post(`/api/notifications/${id}/read`) }
export function markAllNotificationsRead() { return api.post('/api/notifications/read-all') }

// 用户、部门、角色
export function getDepartments() { return api.get('/api/departments') }
export function getRoles() { return api.get('/api/roles') }
export function getUsers(params) { return api.get('/api/users', { params }) }
export function updateUser(id, data) { return api.put(`/api/users/${id}`, data) }
export function resetUserPassword(id, data = {}) { return api.post(`/api/users/${id}/reset-password`, data) }

// 首页仪表盘（旧消息分流管理）
export function getDashboardSummary() { return api.get('/api/dashboard/summary') }

// 消息中心
export function getMessages(limit = 50) { return api.get('/api/messages', { params: { limit } }) }
export function updateMessageStatus(messageId, status) {
  return api.post(`/api/messages/${messageId}/status`, { status })
}

// Dify 工作流管理
export function getWorkflows() { return api.get('/api/workflows') }
export function createWorkflow(data) { return api.post('/api/workflows', data) }
export function updateWorkflow(id, data) { return api.put(`/api/workflows/${id}`, data) }
export function deleteWorkflow(id) { return api.delete(`/api/workflows/${id}`) }
export function testWorkflow(id, data) { return api.post(`/api/workflows/${id}/test`, data) }

// 规则配置
export function getRules() { return api.get('/api/rules') }
export function createRule(data) { return api.post('/api/rules', data) }
export function updateRule(id, data) { return api.put(`/api/rules/${id}`, data) }
export function deleteRule(id) { return api.delete(`/api/rules/${id}`) }

// OA 智能申请
export function recognizeOaIntent(data) { return api.post('/api/oa/intent/recognize', data) }
export function getOaAgentConfig() { return api.get('/api/oa/agent/config') }
export function chatWithOaAgent(data) { return api.post('/api/oa/agent/chat', data) }
export function deleteOaAgentSession(sessionId) { return api.delete(`/api/oa/agent/sessions/${sessionId}`) }
export function createOaApplication(data) { return api.post('/api/oa/applications', data) }
export function listOaApplications(params) { return api.get('/api/oa/applications', { params }) }
export function getOaApplicationDetail(applicationId) { return api.get(`/api/oa/applications/${applicationId}`) }
export function updateOaApplication(applicationId, data) { return api.put(`/api/oa/applications/${applicationId}`, data) }
export function submitOaApplication(applicationId) { return api.post(`/api/oa/applications/${applicationId}/submit`) }
export function deleteOaApplication(applicationId) { return api.delete(`/api/oa/applications/${applicationId}`) }

// OA 审批
export function getPendingApprovals(params) { return api.get('/api/oa/approvals/pending', { params }) }
export function getApprovalHistory(params) { return api.get('/api/oa/approvals/history', { params }) }
export function approveOaApplication(id, data) { return api.post(`/api/oa/applications/${id}/approve`, data) }
export function rejectOaApplication(id, data) { return api.post(`/api/oa/applications/${id}/reject`, data) }


// AI 内部文档检索
export function getDocumentSearchStatus() { return api.get('/api/ai/document-search/status') }
export function searchDocuments(data) { return api.post('/api/ai/document-search', data) }

// AI 智能会议纪要
export function getMeetingMinutesStatus() {
  return api.get('/api/ai/meeting-minutes/status')
}

export function generateMeetingMinutes(formData) {
  return api.post('/api/ai/meeting-minutes/generate', formData, {
    timeout: 900000
  })
}


// AI 员工考核一体化（出题与批阅）
export function getEmployeeAssessmentStatus() {
  return api.get('/api/ai/employee-assessment/status')
}

export function generateEmployeeAssessment(data) {
  return api.post('/api/ai/employee-assessment/generate', data, {
    timeout: 900000
  })
}

export function reviewEmployeeAssessment(formData) {
  return api.post('/api/ai/employee-assessment/review', formData, {
    timeout: 900000
  })
}

// AI 员工考核评估与培训建议
export function getEmployeeAssessmentAnalysisStatus() {
  return api.get('/api/ai/employee-assessment-analysis/status')
}

export function analyzeEmployeeAssessment(data) {
  return api.post('/api/ai/employee-assessment-analysis/analyze', data, {
    timeout: 900000
  })
}

// AI 日报与阶段报表
export function getReportGenerateStatus() {
  return api.get('/api/ai/report-generate/status')
}

export function chatReportGenerate(data) {
  return api.post('/api/ai/report-generate/chat', data, {
    timeout: 900000
  })
}

