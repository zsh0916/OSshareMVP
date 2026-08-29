<template>
  <div class="page-shell dashboard-page">
    <div class="page-title-row standardized-page-head">
      <div>
        <span class="page-kicker">MESSAGE ROUTING</span>
        <h2>消息分流仪表盘</h2>
        <p>查看飞书业务消息分流、优先级、处理与推送情况。</p>
      </div>
    </div>
    <el-row class="dashboard-stats" :gutter="16">
      <el-col :span="4">
        <el-card>
          <div class="stat-label">消息总数</div>
          <div class="stat-number">{{ summary.total }}</div>
        </el-card>
      </el-col>

      <el-col :span="4">
        <el-card>
          <div class="stat-label">P0 紧急</div>
          <div class="stat-number danger">{{ summary.p0 }}</div>
        </el-card>
      </el-col>

      <el-col :span="4">
        <el-card>
          <div class="stat-label">P1 重要</div>
          <div class="stat-number warning">{{ summary.p1 }}</div>
        </el-card>
      </el-col>

      <el-col :span="4">
        <el-card>
          <div class="stat-label">已处理</div>
          <div class="stat-number success">{{ summary.handled }}</div>
        </el-card>
      </el-col>

      <el-col :span="4">
        <el-card>
          <div class="stat-label">AI 误判</div>
          <div class="stat-number danger">{{ summary.wrong_ai_result }}</div>
        </el-card>
      </el-col>

      <el-col :span="4">
        <el-card>
          <div class="stat-label">已推送</div>
          <div class="stat-number primary">{{ summary.sent }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="section-card dashboard-capability-card">
      <template #header>
        <div class="card-header">平台能力概览</div>
      </template>

      <el-timeline>
        <el-timeline-item>飞书群消息实时监听</el-timeline-item>
        <el-timeline-item>本地规则权重打分</el-timeline-item>
        <el-timeline-item>Dify AI 分类、摘要和建议动作</el-timeline-item>
        <el-timeline-item>飞书卡片推送与人工反馈</el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<script setup>
defineProps({
  summary: {
    type: Object,
    required: true
  }
})
</script>

<style scoped>
.page-shell{display:flex;flex-direction:column;gap:20px}.standardized-page-head{display:flex;justify-content:space-between;align-items:flex-end}.page-kicker{color:var(--primary);font-size:11px;font-weight:700;letter-spacing:1.8px}.standardized-page-head h2{margin:7px 0 6px;color:var(--text);font-size:30px}.standardized-page-head p{margin:0;color:var(--muted)}.dashboard-stats :deep(.el-col){margin-bottom:16px}.dashboard-stats :deep(.el-card){min-height:112px}.stat-label{color:var(--muted);font-size:13px}.stat-number{margin-top:10px;color:var(--text);font-size:30px;font-weight:800}.stat-number.danger{color:var(--danger)}.stat-number.warning{color:var(--warning)}.stat-number.success{color:var(--success)}.stat-number.primary{color:var(--primary)}.section-card{margin-top:2px}.card-header{color:var(--text);font-size:18px;font-weight:700}.dashboard-capability-card :deep(.el-timeline-item__content){color:var(--text-soft)!important;font-size:14px}.dashboard-capability-card :deep(.el-timeline-item__node){background:var(--primary)!important}.dashboard-capability-card :deep(.el-timeline-item__tail){border-left-color:var(--border)!important}@media(max-width:1100px){.dashboard-stats :deep(.el-col){max-width:33.333%;flex:0 0 33.333%}}@media(max-width:760px){.dashboard-stats :deep(.el-col){max-width:50%;flex:0 0 50%}}
</style>