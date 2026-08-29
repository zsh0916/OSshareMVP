<template>
  <div class="page-shell message-management-page">
    <div class="page-title-row standardized-page-head">
      <div>
        <span class="page-kicker">MESSAGE CENTER</span>
        <h2>消息中心</h2>
        <p>{{ canManage ? '查看全部飞书消息、AI 分类结果与人工处理状态。' : '查看定向推送到本部门的飞书业务消息。' }}</p>
      </div>
      <el-button type="primary" @click="$emit('refresh')">刷新</el-button>
    </div>
    <el-card class="management-card">
    <template #header>
      <div class="table-header">
        <div>
          <div class="card-header">消息中心</div>
          <div class="card-subtitle">
            {{ canManage ? '全平台消息管理视图' : '显示本部门的新消息与历史消息' }}
          </div>
        </div>


      </div>
    </template>

    <el-table
      :data="messages"
      border
      stripe
      style="width: 100%"
      height="650"
      empty-text="当前没有识别为本部门的业务消息"
    >
      <el-table-column prop="id" label="ID" width="70" />

      <el-table-column label="优先级" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.ai_priority" :type="priorityType(row.ai_priority)">
            {{ row.ai_priority }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>

      <el-table-column prop="ai_category" label="AI分类" width="120" />

      <el-table-column label="所属部门" width="120">
        <template #default="{ row }">
          <span>{{ row.target_department || '-' }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="local_score" label="规则分" width="90" />

      <el-table-column label="消息内容" min-width="260">
        <template #default="{ row }">
          <div class="message-text">{{ row.content_text }}</div>
        </template>
      </el-table-column>

      <el-table-column label="AI摘要" min-width="260">
        <template #default="{ row }">
          <div class="summary-text">{{ row.ai_summary || '-' }}</div>
        </template>
      </el-table-column>

      <el-table-column prop="ai_assignee" label="建议负责人" width="140" />

      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="statusType(row.card_status)">
            {{ statusText(row.card_status) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="created_at" label="时间" width="180" />

      <el-table-column v-if="canManage" label="操作" min-width="250">
        <template #default="{ row }">
          <div class="row-actions">
          <el-button size="small" type="success" @click="changeStatus(row, 'handled')">
            已处理
          </el-button>

          <el-button size="small" type="danger" @click="changeStatus(row, 'wrong_ai_result')">
            误判
          </el-button>

          <el-button size="small" @click="changeStatus(row, 'manual_followup')">
            转人工
          </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { updateMessageStatus } from '../api'

const props = defineProps({
  messages: {
    type: Array,
    required: true
  },
  canManage: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['refresh'])

function priorityType(priority) {
  if (priority === 'P0') return 'danger'
  if (priority === 'P1') return 'warning'
  if (priority === 'P2') return 'primary'
  return 'info'
}

function statusType(status) {
  if (status === 'handled') return 'success'
  if (status === 'wrong_ai_result') return 'danger'
  if (status === 'manual_followup') return 'warning'
  if (status === 'sent') return 'primary'
  return 'info'
}

function statusText(status) {
  const map = {
    handled: '已处理',
    wrong_ai_result: 'AI误判',
    manual_followup: '转人工',
    sent: '已推送',
    platform_notified: '已推送至平台',
    no_department_route: '未配置部门路由',
    send_failed: '推送失败',
    not_pushed_low_score: '低分未推送',
    ignored_not_target_chat: '非目标群',
    ignored_bot_message: '机器人消息'
  }

  return map[status] || status || '未知'
}

async function changeStatus(row, status) {
  if (!props.canManage) {
    ElMessage.warning('当前账号仅有本部门消息查看权限')
    return
  }

  try {
    await updateMessageStatus(row.message_id, status)
    ElMessage.success('状态已更新')
    emit('refresh')
  } catch (e) {
    console.error(e)
    ElMessage.error('状态更新失败')
  }
}
</script>

<style scoped>
.page-shell{display:flex;flex-direction:column;gap:20px}.standardized-page-head{display:flex;justify-content:space-between;align-items:flex-end}.page-kicker{color:var(--primary);font-size:11px;font-weight:700;letter-spacing:1.8px}.standardized-page-head h2{margin:7px 0 6px;color:var(--text);font-size:30px}.standardized-page-head p{margin:0;color:var(--muted)}.row-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.row-actions :deep(.el-button){margin-left:0!important}.message-text,.summary-text{color:var(--text-soft);line-height:1.6;word-break:break-word}@media(max-width:800px){.standardized-page-head{align-items:flex-start;flex-direction:column}}
</style>
