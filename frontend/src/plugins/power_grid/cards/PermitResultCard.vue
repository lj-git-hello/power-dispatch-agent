<script setup lang="ts">
/**
 * PermitResultCard —— 终态调度许可凭证卡片（业务插件）。
 *
 * 展示调度令编号、许可时间、CA 签名摘要，并将签名渲染为现场核验二维码。
 */
import { computed } from 'vue'
import QrcodeVue from 'qrcode.vue'

import type { ChatMessageRecord } from '@/core/a2ui/types'

interface PermitInfo {
  permit_no: string
  ca_signature_hash: string
  issued_at: string
}

const props = defineProps<{
  message: ChatMessageRecord
}>()

const payload = computed<Record<string, unknown>>(
  () => props.message.card_payload ?? {},
)

const permitInfo = computed<PermitInfo | null>(
  () => (payload.value.permit_info as PermitInfo | undefined) ?? null,
)

const status = computed(() => String(payload.value.status ?? ''))

// 二维码内容：签名摘要（附编号保证唯一性）
const qrValue = computed(() => {
  const info = permitInfo.value
  return info ? `${info.permit_no}|${info.ca_signature_hash}` : ''
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex items-center justify-between">
      <p class="text-sm font-medium text-gray-800">调度许可凭证</p>
      <span
        class="rounded-full px-2 py-0.5 text-[10px]"
        :class="
          status === 'PERMITTED'
            ? 'bg-green-100 text-green-700'
            : 'bg-gray-100 text-gray-600'
        ">{{ status }}</span>
    </div>

    <template v-if="permitInfo">
      <dl class="flex flex-col gap-1 text-xs text-gray-600">
        <div class="flex gap-2">
          <dt class="shrink-0 text-gray-400">调度令编号：</dt>
          <dd class="break-all">{{ permitInfo.permit_no }}</dd>
        </div>
        <div class="flex gap-2">
          <dt class="shrink-0 text-gray-400">许可时间：</dt>
          <dd>{{ permitInfo.issued_at }}</dd>
        </div>
        <div class="flex gap-2">
          <dt class="shrink-0 text-gray-400">CA 签名：</dt>
          <dd class="break-all font-mono text-[10px]">
            {{ permitInfo.ca_signature_hash.slice(0, 24) }}…
          </dd>
        </div>
      </dl>

      <div class="flex justify-center rounded-md border border-gray-200 bg-white p-2">
        <QrcodeVue
          :value="qrValue"
          :size="120"
          level="M"
          render-as="svg"
        />
      </div>
      <p class="text-center text-[10px] text-gray-400">现场扫码核验凭证</p>
    </template>

    <p v-else class="text-xs text-gray-400">暂无许可信息</p>
  </div>
</template>
