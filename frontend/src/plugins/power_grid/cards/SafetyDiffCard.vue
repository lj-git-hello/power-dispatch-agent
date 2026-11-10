<script setup lang="ts">
/**
 * SafetyDiffCard —— 安全合规差异审核卡片（业务插件）。
 *
 * 展示电压等级、变电站、违规隐患；核准/驳回经 useWorkflowAction.submitAudit
 * 直接提交后端字段（is_permitted/opinion），携带 thread_id/lock_version；
 * 409 冲突时轻提示并通知父级剔除失效项。
 */
import { computed } from 'vue'

import { useWorkflowAction } from '@/core/composables/useWorkflowAction'
import type { ChatMessageRecord } from '@/core/a2ui/types'

const props = defineProps<{
  message: ChatMessageRecord
}>()

const emit = defineEmits<{
  conflict: []
  decided: [permitted: boolean]
}>()

const payload = computed<Record<string, unknown>>(
  () => props.message.card_payload ?? {},
)

const threadId = computed(() => String(payload.value.thread_id ?? ''))
const lockVersion = computed(
  () => Number(payload.value.lock_version ?? 0),
)
const substation = computed(() => String(payload.value.substation ?? ''))
const voltageLevel = computed(
  () => String(payload.value.voltage_level ?? ''),
)
const violations = computed<string[]>(
  () => (payload.value.violations as string[] | undefined) ?? [],
)

const AUDIT_URL = '/v1/power-dispatch/audit'

const { isSubmitting, notice, submitAudit } = useWorkflowAction()

async function decide(permitted: boolean) {
  await submitAudit(
    AUDIT_URL,
    {
      thread_id: threadId.value,
      lock_version: lockVersion.value,
      is_permitted: permitted,
      opinion: permitted ? '核准许可' : '驳回修改',
    },
    // 成功
    () => emit('decided', permitted),
    // 409：轻提示并让父级移除该失效项
    () => emit('conflict'),
  )
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="text-sm">
      <p class="font-medium text-gray-800">{{ substation }}</p>
      <p class="mt-0.5 text-xs text-gray-500">
        电压等级：{{ voltageLevel }}
      </p>
    </div>

    <!-- 风险隐患 -->
    <div class="rounded-md bg-amber-50 p-2">
      <p class="text-xs font-medium text-amber-700">合规校验结果</p>
      <ul
        v-if="violations.length"
        class="mt-1 list-disc pl-4 text-xs text-amber-700"
      >
        <li v-for="item in violations" :key="item">{{ item }}</li>
      </ul>
      <p v-else class="mt-1 text-xs text-green-700">
        安措齐备，未发现违规项
      </p>
    </div>

    <!-- CAS 冲突提示 -->
    <p v-if="notice?.type === 'conflict'" class="text-xs text-amber-600">
      【冲突拦截】该工单已被其他操作人处理或版本已失效
    </p>

    <div class="flex gap-2">
      <button
        type="button"
        class="flex-1 rounded-md bg-green-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        :disabled="isSubmitting"
        @click="decide(true)"
      >
        核准许可
      </button>
      <button
        type="button"
        class="flex-1 rounded-md bg-gray-200 px-3 py-1.5 text-sm text-gray-700 disabled:opacity-50"
        :disabled="isSubmitting"
        @click="decide(false)"
      >
        驳回修改
      </button>
    </div>
  </div>
</template>
