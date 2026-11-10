/**
 * Storage —— 基于 localforage(IndexedDB) 的会话消息本地持久化。
 *
 * 按 session_id 存取消息记录；推流结束后用 1000ms 防抖写入，
 * 避免流式过程中频繁写库。
 */

import localforage from 'localforage'

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

function sessionKey(sessionId: string): string {
  return `session:${sessionId}`
}

/** 立即保存某会话的消息。 */
export async function saveMessages<T>(sessionId: string, messages: T): Promise<T> {
  const envelope: MessageEnvelope<T> = { updatedAt: Date.now(), messages }
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
    void saveMessages(sessionId, messages)
  }, SAVE_DEBOUNCE_MS)

  debounceTimers.set(sessionId, timer)
}
