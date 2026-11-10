<script setup lang="ts">
/**
 * TaskHistoryList —— 提报员历史时间线（通用）。
 *
 * 加载时从 IndexedDB 读取离线历史；文本渲染气泡，卡片经 MessageCardHost；
 * 消息变更时防抖持久化。
 */
import { onMounted, ref, watch } from 'vue'

import MessageCardHost from '../a2ui/MessageCardHost.vue'
import type { CardActionContext, ChatMessageRecord } from '../a2ui/types'
import {
  debounceSaveMessages,
  loadMessages,
} from '../engine/storage'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  sessionId: string
  currentUserId: string
}>()

const messages = ref<ChatMessageRecord[]>([])

// 卡片动作上下文（本视图内 dispatch 仅占位，业务动作由后续注入）
function makeActionContext(message: ChatMessageRecord): CardActionContext {
  return {
    threadId: message.thread_id,
    retryPayload: message.retry_payload,
    dispatch: () => undefined,
  }
}

function textHtml(message: ChatMessageRecord): string {
  return renderMarkdown(message.content ?? '')
}

async function hydrate() {
  const stored = await loadMessages<ChatMessageRecord[]>(props.sessionId)
  if (stored) messages.value = stored
}

// 变更防抖落盘（深度监听）
watch(
  messages,
  (list) => debounceSaveMessages(props.sessionId, list),
  { deep: true },
)

onMounted(hydrate)

// 暴露给父组件追加消息
defineExpose({ messages })
</script>

<template>
  <div class="flex h-full flex-col gap-3 overflow-y-auto p-4">
    <p v-if="messages.length === 0" class="text-sm text-gray-400">
      暂无历史消息
    </p>

    <div
      v-for="message in messages"
      :key="message.id"
      class="flex"
      :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
    >
      <!-- 卡片类型 -->
      <div
        v-if="message.kind === 'card'"
        class="w-full max-w-md rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
      >
        <MessageCardHost
          :message="message"
          :action-context="makeActionContext(message)"
        />
      </div>

      <!-- 文本气泡 -->
      <div
        v-else
        class="max-w-md rounded-lg px-3 py-2 text-sm"
        :class="
          message.role === 'user'
            ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-800'
        "
        v-html="textHtml(message)"
      />
    </div>
  </div>
</template>
