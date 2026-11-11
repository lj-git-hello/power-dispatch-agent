/**
 * useWorkbenchStore —— 通用三栏工作台共享响应式状态（跨业务、零业务词）。
 *
 * 收口中栏消息、左栏会话集合、右栏抽屉开合；两套数据源严格隔离：
 * - conversationList：当前用户【我的会话】集合，按用户持久化到 IndexedDB；
 * - 待办审批池：由审批池视图在 Tab 激活时独立请求后端，不进入本 store。
 *
 * applyResult 将后端返回的卡片快照转为消息并刷新会话集合、折叠抽屉。
 */

import { reactive, watch } from 'vue'

import type {
  ChatMessageRecord,
  TaskSummary,
} from '../a2ui/types'
import {
  debounceSaveConversations,
  loadConversations,
  loadMessages,
} from '../engine/storage'

/** apply 端点返回结构（本 store 只依赖通用形态） */
export interface ApplyResult {
  thread_id: string
  status: string
  card: Record<string, unknown>
}

interface WorkbenchState {
  activeSessionId: string
  activeMessages: ChatMessageRecord[]
  conversationList: TaskSummary[]
  rightDrawerOpen: boolean
}

const state = reactive<WorkbenchState>({
  activeSessionId: '',
  activeMessages: [],
  conversationList: [],
  rightDrawerOpen: true,
})

/** 会话集合归属用户（切换身份时随之切换并重新 hydrate）。 */
let conversationOwnerId: string | null = null

/** 切换当前会话：替换会话 ID 与消息列表（hydrate 由调用方在外部完成后写入）。 */
function setSession(sessionId: string, messages: ChatMessageRecord[] = []) {
  state.activeSessionId = sessionId
  state.activeMessages.splice(0, state.activeMessages.length, ...messages)
}

/** 直接追加一条消息（外部 hydrate / 文本回执均可）。 */
function appendMessage(message: ChatMessageRecord) {
  state.activeMessages.push(message)
}

/** 选中某条会话：切换到其 session_id 并从 IndexedDB 恢复消息。 */
async function openConversation(summary: TaskSummary) {
  const stored = await loadMessages<ChatMessageRecord[]>(summary.session_id)
  setSession(summary.session_id, stored ?? [])
}

/**
 * 加载指定用户的会话集合；身份切换时调用。
 * 仅当归属用户变化时才重新拉取，避免覆盖内存中的新记录。
 */
async function hydrateConversations(userId: string) {
  if (conversationOwnerId === userId) return
  conversationOwnerId = userId
  const stored = await loadConversations<TaskSummary[]>(userId)
  state.conversationList.splice(
    0,
    state.conversationList.length,
    ...(stored ?? []),
  )
}

/** 把后端 apply 返回结果收口为：中栏卡片消息 + 会话集合 upsert + 折叠右栏。 */
function applyResult(result: ApplyResult) {
  const card = result.card ?? {}
  const cardType = String(card.card_type ?? '')

  // 中栏：卡片快照消息（MessageCardHost 据 card_type 动态渲染）
  const message: ChatMessageRecord = {
    id: crypto.randomUUID(),
    thread_id: result.thread_id,
    role: 'assistant',
    kind: 'card',
    content: null,
    card_type: cardType,
    card_payload: card,
    retry_payload: null,
    created_at: new Date().toISOString(),
  }
  state.activeMessages.push(message)

  // 左栏：追加或更新该会话（去重：同 thread_id 覆盖）
  const existingIndex = state.conversationList.findIndex(
    (item) => item.thread_id === result.thread_id,
  )
  const summary: TaskSummary = {
    thread_id: result.thread_id,
    session_id: state.activeSessionId,
    creator_id: '',
    assigned_role: '',
    status: result.status || 'WAITING_HUMAN',
    lock_version: Number(card.lock_version ?? 1),
    current_node: null,
    // 通用取标题：装配层可在 card.title 注入业务标题；缺省回退展示 thread_id
    title:
      typeof card.title === 'string' && card.title
        ? card.title
        : undefined,
  }
  if (existingIndex >= 0) {
    state.conversationList.splice(existingIndex, 1, summary)
  } else {
    state.conversationList.unshift(summary)
  }

  // 右栏：折叠抽屉
  state.rightDrawerOpen = false
}

/** 整体替换左栏列表（切换身份 / 拉取后刷新）。 */
function setConversations(list: TaskSummary[]) {
  state.conversationList.splice(0, state.conversationList.length, ...list)
}

/** 设置右栏抽屉开合。 */
function setRightDrawer(open: boolean) {
  state.rightDrawerOpen = open
}

// 会话集合变更（含提报成功 upsert）→ 按归属用户防抖落盘
watch(
  () => state.conversationList,
  (list) => {
    if (conversationOwnerId) {
      debounceSaveConversations(conversationOwnerId, [...list])
    }
  },
  { deep: true },
)

export function useWorkbenchStore() {
  return {
    state,
    setSession,
    appendMessage,
    openConversation,
    hydrateConversations,
    applyResult,
    setConversations,
    setRightDrawer,
  }
}
