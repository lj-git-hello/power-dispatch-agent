/**
 * a2ui 类型 —— 与后端 ai_chat_messages 记录结构对齐。
 */

/** 消息种类：文本 / 卡片 */
export type MessageKind = 'text' | 'card'

/** 消息记录（对应后端 AIChatMessage） */
export interface ChatMessageRecord {
  id: string
  thread_id: string
  role: string
  kind: MessageKind
  content: string | null
  card_type: string | null
  card_payload: Record<string, unknown> | null
  retry_payload: Record<string, unknown> | null
  created_at: string | null
}

/** 卡片交互上下文：卡片动作回调可据此触发重试/上报 */
export interface CardActionContext {
  threadId: string
  /** 自包含重试载荷（来自后端 retry_payload） */
  retryPayload: Record<string, unknown> | null
  /** 触发某个动作（由宿主/业务注入具体实现） */
  dispatch: (action: string, payload?: Record<string, unknown>) => void
}

/** 卡片组件接收的 props（各业务卡片统一契约） */
export interface CardComponentProps {
  message: ChatMessageRecord
  actionContext: CardActionContext
}
