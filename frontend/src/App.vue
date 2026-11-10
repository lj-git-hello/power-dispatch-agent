<script setup lang="ts">
/**
 * App —— 装配层：将电力业务插件的表单与端点注入通用工作台，
 * 并把表单提交成功事件收口到布局的联动处理。
 */
import { ref } from 'vue'

import WorkbenchLayout from './core/views/WorkbenchLayout.vue'
import type { ApplyResult } from './core/workbench/useWorkbenchStore'
import {
  POWER_ENDPOINTS,
  SubstationApplyForm,
} from './plugins/power_grid'

// 工作台布局实例
const layoutRef = ref<InstanceType<typeof WorkbenchLayout> | null>(null)

function handleSubmitted(result: ApplyResult) {
  layoutRef.value?.handleApplied(result)
}
</script>

<template>
  <WorkbenchLayout ref="layoutRef" :endpoints="POWER_ENDPOINTS">
    <!-- 业务表单挂到底座插槽（sessionId 由插槽作用域提供） -->
    <template #business-form="{ sessionId }">
      <SubstationApplyForm
        :session-id="sessionId"
        @submitted="handleSubmitted"
      />
    </template>
  </WorkbenchLayout>
</template>