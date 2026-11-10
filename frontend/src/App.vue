<script setup lang="ts">
/**
 * App —— 装配层：将电力业务插件的表单与端点注入通用工作台。
 */
import WorkbenchLayout from './core/views/WorkbenchLayout.vue'
import {
  POWER_ENDPOINTS,
  SubstationApplyForm,
} from './plugins/power_grid'
</script>

<template>
  <WorkbenchLayout :endpoints="POWER_ENDPOINTS">
    <!-- 业务表单挂到底座插槽（sessionId 由插槽作用域提供） -->
    <template #business-form="{ sessionId }">
      <SubstationApplyForm :session-id="sessionId" />
    </template>
  </WorkbenchLayout>
</template>
