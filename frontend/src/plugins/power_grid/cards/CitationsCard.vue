<script setup lang="ts">
/**
 * CitationsCard —— 规程引文卡片（业务插件）。
 *
 * 由通用对话网关下发的 ui_card 事件渲染：
 * card_payload = { citations: [{ doc_code, section_title, content, similarity }] }
 */
import { computed } from 'vue'

import type { ChatMessageRecord } from '@/core/a2ui/types'

const props = defineProps<{
  message: ChatMessageRecord
}>()

interface CitationItem {
  doc_code: string
  section_title: string | null
  content: string
  similarity: number
}

const citations = computed<CitationItem[]>(() => {
  const payload = props.message.card_payload ?? {}
  const raw = (payload as { citations?: unknown }).citations
  return Array.isArray(raw) ? (raw as CitationItem[]) : []
})

/** 相似度转百分比展示 */
function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <p class="text-xs font-medium text-gray-600">
      规程依据（{{ citations.length }} 条）
    </p>

    <p v-if="citations.length === 0" class="text-xs text-gray-400">
      未检索到相关条款
    </p>

    <div
      v-for="(item, index) in citations"
      :key="`${item.doc_code}-${index}`"
      class="rounded-md border border-gray-200 bg-gray-50 p-2"
    >
      <p class="text-xs font-medium text-gray-700">
        【{{ item.doc_code
        }}<template v-if="item.section_title">
          / {{ item.section_title }}</template>】
        <span class="ml-1 text-[10px] text-gray-400">
          相似度 {{ percent(item.similarity) }}
        </span>
      </p>
      <p class="mt-1 whitespace-pre-wrap text-xs text-gray-600">
        {{ item.content }}
      </p>
    </div>
  </div>
</template>
