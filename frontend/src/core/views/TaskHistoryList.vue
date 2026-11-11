<script setup lang="ts">
/**
 * TaskHistoryList —— 提报员历史时间线（通用）。
 *
 * 渲染源由外部（工作台 store）经 props.messages 传入；挂载时从 IndexedDB
 * 离线恢复，文本渲染气泡，卡片经 MessageCardHost；消息变更防抖持久化。
 */
import { onMounted } from 'vue'

import MessageCardHost from '../a2ui/MessageCardHost.vue'
import type { CardActionContext, ChatMessageRecord } from '../a2ui/types'
import { loadMessages } from '../engine/storage'
import { renderMarkdown } from '@/core/utils/markdown'

const props = defineProps<{
  sessionId: string
  currentUserId: string
  /** 外部响应式消息列表（store 持有） */
  messages: ChatMessageRecord[]
}>()

// 卡片动作上下文（dispatch 占位，业务动作后续注入）
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
  if (stored) props.messages.splice(0, props.messages.length, ...stored)
}

// 持久化责任已收敛到 useWorkbenchStore（避免切换 Tab 时漏写），
// 本视图只负责离线恢复与渲染。
onMounted(hydrate)
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