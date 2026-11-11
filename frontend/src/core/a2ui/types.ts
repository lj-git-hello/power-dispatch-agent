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

/**
 * ResumeActionContext —— CAS 恢复动作上下文。
 * 提交给工作流恢复端点，用于乐观锁版本校验。
 */
export interface ResumeActionContext {
  thread_id: string
  lock_version: number
  action: string
  payload: Record<string, unknown> | null
}

/** 任务 / 会话摘要：列表与看板使用的通用结构 */
export interface TaskSummary {
  thread_id: string
  session_id: string
  creator_id: string
  assigned_role: string
  status: string
  lock_version: number
  current_node: string | null
  /** 列表展示标题（可缺省，回退展示 thread_id） */
  title?: string
}

/**
 * WorkflowEndpoints —— 工作流端点配置（依赖反转）。
 * 由各业务插件提供具体 URL，core 视图不写死任何业务路径。
 */
export interface WorkflowEndpoints {
  /** 待办列表端点 */
  tasks: string
  /** 某线程消息端点 */
  messages: string
  /** 恢复/核签端点 */
  resume: string
}
