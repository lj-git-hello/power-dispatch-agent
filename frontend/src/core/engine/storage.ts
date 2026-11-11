/**
 * Storage —— 基于 localforage(IndexedDB) 的会话消息本地持久化。
 *
 * 按 session_id 存取消息记录；推流结束后用 1000ms 防抖写入，
 * 避免流式过程中频繁写库。
 */

import localforage from 'localforage'
import { isReactive, toRaw } from 'vue'

/** 防抖持久化延迟（毫秒） */
const SAVE_DEBOUNCE_MS = 1000

/** 专用 localforage 实例，与其它本地存储隔离 */
const messageStore = localforage.createInstance({
  name: 'agent-scaffold',
  storeName: 'messages',
  description: '会话消息记录',
})

/** 存储值包装：附带更新时间，便于排查 */
interface MessageEnvelope<T> {
  updatedAt: number
  messages: T
}

/**
 * 深度去响应式：把 Vue 响应式代理还原为纯 JS 对象。
 *
 * IndexedDB 使用结构化克隆（structured clone），遇到 Proxy 会抛
 * DataCloneError，因此落盘前必须剥离响应式代理。
 */
function deepToPlain<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => deepToPlain(item)) as unknown as T
  }
  if (value !== null && typeof value === 'object') {
    const raw = isReactive(value) ? toRaw(value) : value
    const result: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(raw as Record<string, unknown>)) {
      result[key] = deepToPlain(item)
    }
    return result as T
  }
  return value
}

function sessionKey(sessionId: string): string {
  return `session:${sessionId}`
}

/** 立即保存某会话的消息。 */
export async function saveMessages<T>(sessionId: string, messages: T): Promise<T> {
  const envelope: MessageEnvelope<T> = {
    updatedAt: Date.now(),
    messages: deepToPlain(messages),
  }
  await messageStore.setItem(sessionKey(sessionId), envelope)
  return messages
}

/** 读取某会话的消息；不存在时返回 null。 */
export async function loadMessages<T>(sessionId: string): Promise<T | null> {
  const envelope = await messageStore.getItem<MessageEnvelope<T>>(sessionKey(sessionId))
  return envelope ? envelope.messages : null
}

/** 清除某会话的本地记录。 */
export async function clearSession(sessionId: string): Promise<void> {
  await messageStore.removeItem(sessionKey(sessionId))
}

// ---------------------------------------------------------------------------
// 会话 / 工单集合（左栏【我的会话】），按用户隔离持久化
// ---------------------------------------------------------------------------

function conversationsKey(userId: string): string {
  return `conversations:${userId}`
}

/** 保存某用户的会话集合。 */
export async function saveConversations<T>(userId: string, list: T): Promise<T> {
  // 与消息落盘同理：集合元素仍可能是 Vue 响应式代理，
  // 结构化克隆会抛 DataCloneError，必须先深剥离。
  const envelope: MessageEnvelope<T> = {
    updatedAt: Date.now(),
    messages: deepToPlain(list),
  }
  await messageStore.setItem(conversationsKey(userId), envelope)
  return list
}

/** 读取某用户的会话集合；不存在时返回 null。 */
export async function loadConversations<T>(userId: string): Promise<T | null> {
  const envelope = await messageStore.getItem<MessageEnvelope<T>>(conversationsKey(userId))
  return envelope ? envelope.messages : null
}

/** 集合持久化防抖（按用户隔离）。 */
const conversationTimers = new Map<string, ReturnType<typeof setTimeout>>()

export function debounceSaveConversations<T>(userId: string, list: T): void {
  const existingTimer = conversationTimers.get(userId)
  if (existingTimer) clearTimeout(existingTimer)

  const timer = setTimeout(() => {
    conversationTimers.delete(userId)
    // 落盘失败必须显式可见：静默失败会让"刷新后数据消失"变成无头案
    void saveConversations(userId, list).catch((error: unknown) => {
      console.error('[本地持久化] 会话集合写入失败：', error)
    })
  }, SAVE_DEBOUNCE_MS)

  conversationTimers.set(userId, timer)
}

/** 已注册的防抖计时器（按会话隔离） */
const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>()

/**
 * 防抖持久化：在最后一次调用后等待 1000ms 再真正写入。
 * 推流期间连续调用会不断重置计时器，done 后落盘一次。
 */
export function debounceSaveMessages<T>(sessionId: string, messages: T): void {
  const existingTimer = debounceTimers.get(sessionId)
  if (existingTimer) clearTimeout(existingTimer)

  const timer = setTimeout(() => {
    debounceTimers.delete(sessionId)
    // 落盘失败必须显式可见：静默失败会让"刷新后数据消失"变成无头案
    void saveMessages(sessionId, messages).catch((error: unknown) => {
      console.error('[本地持久化] 消息写入失败：', error)
    })
  }, SAVE_DEBOUNCE_MS)

  debounceTimers.set(sessionId, timer)
}
