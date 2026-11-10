<script setup lang="ts">
/**
 * MessageCardHost —— 卡片宿主。
 *
 * 根据 message.card_type 从 CardRegistry 动态解析卡片组件；
 * 未注册时渲染 JSON 兜底卡片，保证消息始终可读、不白屏。
 */
import { computed } from 'vue'

import { CardRegistry } from './CardRegistry'
import type { CardActionContext, ChatMessageRecord } from './types'

const props = defineProps<{
  message: ChatMessageRecord
  actionContext?: CardActionContext
}>()

// 动态组件（未注册时为 undefined → 走兜底）
const resolved = computed(() =>
  props.message.card_type ? CardRegistry.get(props.message.card_type) : undefined,
)

// 兜底展示的 JSON 文本
const fallbackJson = computed(() =>
  JSON.stringify(props.message.card_payload ?? {}, null, 2),
)
</script>

<template>
  <div class="w-full">
    <component
      :is="resolved"
      v-if="resolved"
      :message="message"
      :action-context="actionContext"
    />

    <!-- 未注册卡片：JSON 兜底 -->
    <div
      v-else
      class="rounded-md border border-dashed border-gray-300 bg-gray-50 p-3"
    >
      <p class="mb-2 text-xs text-gray-500">
        未注册卡片类型：{{ message.card_type ?? '（空）' }}
      </p>
      <pre
        class="overflow-x-auto whitespace-pre-wrap break-all text-xs text-gray-700">{{ fallbackJson }}</pre>
    </div>
  </div>
</template>
