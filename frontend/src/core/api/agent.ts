/**
 * agent —— 通用 A2UI 流式对话客户端（跨业务、零业务词汇）。
 *
 * 采用 @microsoft/fetch-event-source（项目规范指定的成熟事件流驱动库）：
 * 库内置事件分帧、TCP Buffer 拼接与断网自动重连；
 * 其 EventSourceMessage.event 会透传 SSE 的 event: 字段，可直接用于事件分派。
 *
 * 事件契约与后端 app/schemas/a2ui.py 的 A2UIEventType 对齐：
 * token（增量文本）/ ui_card（结构化卡片）/ error（异常降级）/ done（终结）。
 */

import { fetchEventSource } from '@microsoft/fetch-event-source'

import { API_BASE, TOKEN_STORAGE_KEY } from './http'

/** 通用对话流端点（相对 /api） */
export const CHAT_STREAM_PATH = '/v1/agent/chat-stream'

/** 流事件类型（与后端 A2UIEventType 一一对应） */
export type ChatEventType = 'token' | 'ui_card' | 'error' | 'done'

/** 对话流请求体 */
export interface ChatStreamRequest {
  thread_id: string
  session_id: string
  message: string
}

/** 扁平事件负载 */
export interface AgentChatEvent {
  type: ChatEventType
  content?: string | null
  card_type?: string | null
  data?: Record<string, unknown> | null
  message?: string | null
}

/** 流连接状态（驱动界面状态灯） */
export type StreamStatus = 'connected' | 'reconnecting' | 'offline'

/** 事件回调集合 */
export interface ChatStreamHandlers {
  onToken?: (content: string) => void
  onCard?: (cardType: string, data: Record<string, unknown>) => void
  onError?: (message: string) => void
  onDone?: () => void
  onStatus?: (status: StreamStatus) => void
}

/** 断线重连间隔（毫秒） */
export const RECONNECT_INTERVAL_MS = 2000
/** 最大重连次数（超过则判定为离线，停止重试，避免重复投递消息） */
export const MAX_RECONNECT_ATTEMPTS = 3

/** 带 fatal 标记的错误：立即终止重连 */
interface FatalStreamError extends Error {
  fatal?: boolean
}

function isFatal(error: unknown): boolean {
  return (error as FatalStreamError | null)?.fatal === true
}

/**
 * 发起一次 A2UI 流式对话。
 *
 * @param request 请求体（线程 / 会话 / 文本）
 * @param handlers 事件回调
 * @param signal 外部取消信号
 */
export async function chatStream(
  request: ChatStreamRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
  let retryCount = 0
  /** 流是否正常收到 done 事件（用于区分"正常结束"与"异常断开"） */
  let finished = false

  const dispatch = (payload: AgentChatEvent): void => {
    switch (payload.type) {
      case 'token':
        if (payload.content) {
          handlers.onToken?.(payload.content)
        }
        break
      case 'ui_card':
        if (payload.card_type) {
          handlers.onCard?.(
            payload.card_type,
            payload.data ?? {},
          )
        }
        break
      case 'error':
        handlers.onError?.(payload.message ?? '对话执行异常')
        break
      case 'done':
        finished = true
        handlers.onDone?.()
        break
    }
  }

  await fetchEventSource(`${API_BASE}${CHAT_STREAM_PATH}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(request),
    signal,
    openWhenHidden: true,
    onopen: async (response) => {
      if (!response.ok) {
        const error: FatalStreamError = new Error(
          `对话流建立失败（HTTP ${response.status}）`,
        )
        error.fatal = true
        throw error
      }
      const contentType = response.headers.get('content-type') ?? ''
      if (!contentType.startsWith('text/event-stream')) {
        const error: FatalStreamError = new Error(
          `响应不是 SSE 流（Content-Type=${contentType}）`,
        )
        error.fatal = true
        throw error
      }
      retryCount = 0
      handlers.onStatus?.('connected')
    },
    onmessage: (message) => {
      if (!message.data) {
        return
      }
      let payload: AgentChatEvent
      try {
        payload = JSON.parse(message.data) as AgentChatEvent
      } catch {
        // 非 JSON 负载（如心跳注释）直接忽略，不中断流
        return
      }
      dispatch(payload)
    },
    onerror: (error) => {
      retryCount += 1
      if (isFatal(error) || retryCount > MAX_RECONNECT_ATTEMPTS) {
        handlers.onStatus?.('offline')
        // 抛出以终止库内置重连（返回 false 不会停止重试）
        throw error
      }
      handlers.onStatus?.('reconnecting')
      return RECONNECT_INTERVAL_MS
    },
    onclose: () => {
      // 收到 done 事件属正常收口：后端仍可达，状态灯保持连通；
      // 未收到 done 即断开才判定为离线。
      handlers.onStatus?.(finished ? 'connected' : 'offline')
    },
  })
}
