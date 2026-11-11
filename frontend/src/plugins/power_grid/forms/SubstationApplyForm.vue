<script setup lang="ts">
/**
 * SubstationApplyForm —— 电力检修申报表单（业务插件）。
 *
 * 填写变电站/电压/工作内容/安全措施，提交到后端 apply 端点；
 * 成功后通知父级刷新并可折叠抽屉。
 */
import { computed, reactive, ref } from 'vue'

import { http } from '@/core/api/http'
import { PluginRegistry } from '@/core/plugins/registry'
import type { ApplyResult } from '@/core/workbench/useWorkbenchStore'

const props = defineProps<{
  sessionId: string
}>()

/** apply 成功返回的完整载荷（结构由通用层定义，插件不另立契约） */

const emit = defineEmits<{
  submitted: [result: ApplyResult]
}>()

// 可选安全措施（勾选）
const MEASURE_OPTIONS = [
  '停电后验电确认无电压',
  '在可能来电各端挂设双重接地线',
  '在操作把手悬挂“禁止合闸”标示牌',
] as const

const form = reactive({
  substation: '220kV 云山变电站',
  voltage_level: '220kV',
  operation_task: '',
  selectedMeasures: [true, true, false] as boolean[],
})

const isSubmitting = ref(false)
const errorMessage = ref<string | null>(null)

// 提报端点由插件注册表下发（后端 manifest 为唯一真相源）
const applyUrl = computed(
  () => PluginRegistry.getActive()?.endpoints.apply ?? '',
)

function selectedMeasureTexts(): string[] {
  return MEASURE_OPTIONS.filter((_, index) => form.selectedMeasures[index])
}

async function submit() {
  if (!applyUrl.value) {
    errorMessage.value = '提报端点未配置，请检查业务插件注册状态。'
    return
  }
  isSubmitting.value = true
  errorMessage.value = null

  try {
    const { data } = await http.post<ApplyResult>(
      applyUrl.value,
      {
        session_id: props.sessionId,
        substation: form.substation,
        voltage_level: form.voltage_level,
        operation_task: form.operation_task,
        safety_measures: selectedMeasureTexts(),
      },
    )
    // 回传完整响应（含 card 快照），交由工作台收口联动
    emit('submitted', data)
  } catch (error) {
    errorMessage.value = (error as { message?: string }).message ?? '提交失败'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <form class="flex flex-col gap-3" @submit.prevent="submit">
    <div>
      <label class="mb-1 block text-xs text-gray-500">变电站名称</label>
      <input
        v-model="form.substation"
        type="text"
        class="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
      />
    </div>

    <div>
      <label class="mb-1 block text-xs text-gray-500">电压等级</label>
      <input
        v-model="form.voltage_level"
        type="text"
        class="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
      />
    </div>

    <div>
      <label class="mb-1 block text-xs text-gray-500">工作内容</label>
      <textarea
        v-model="form.operation_task"
        rows="3"
        class="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
        placeholder="如：主变压器停电检修"
      />
    </div>

    <div>
      <label class="mb-1 block text-xs text-gray-500">安全措施</label>
      <div class="flex flex-col gap-1">
        <label
          v-for="(option, index) in MEASURE_OPTIONS"
          :key="option"
          class="flex items-center gap-2 text-xs text-gray-700"
        >
          <input v-model="form.selectedMeasures[index]" type="checkbox" />
          {{ option }}
        </label>
      </div>
    </div>

    <p v-if="errorMessage" class="text-xs text-red-600">
      {{ errorMessage }}
    </p>

    <button
      type="submit"
      class="rounded-md bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50"
      :disabled="isSubmitting"
    >
      {{ isSubmitting ? '提交中…' : '提交智能审查' }}
    </button>
  </form>
</template>
