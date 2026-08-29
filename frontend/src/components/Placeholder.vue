<template>
  <el-card shadow="never" class="placeholder-card">
    <el-empty>
      <template #description>
        <div class="placeholder-title">{{ title }}</div>
        <div class="placeholder-desc">{{ description }}</div>
      </template>
    </el-empty>
  </el-card>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: '功能建设中'
  },
  description: {
    type: String,
    default: '该功能页面已预留，后续继续完善。'
  }
})
</script>

<style scoped>
.placeholder-card {
  min-height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-title {
  font-size: 18px;
  font-weight: 600;
  color: #101828;
}

.placeholder-desc {
  margin-top: 8px;
  font-size: 14px;
  color: #667085;
}
</style>