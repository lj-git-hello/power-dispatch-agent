import { fetchEventSource } from '@microsoft/fetch-event-source';

// ============================================================
// A2UI 协议常量与严格类型定义（禁止 any）
// ============================================================

/** 后端网关地址（开发环境直连 uvicorn，生产可替换为网关域名） */
export const API_BASE_URL = 'http://127.0.0.1:8000';

/** A2UI 聚合网关端点 */
const AGENT_CHAT_STREAM_PATH = '/api/v1/agent/chat-stream';

/** 当前操作角色：运检提报员 / 调度控制长 */
export type RoleType = 'APPLICANT' | 'DISPATCHER';

/** 前端卡片操作回传载荷（唤醒状态机断点恢复） */
export interface AgentActionPayload {
  is_permitted: boolean;
  reason?: string;
}

/** A2UI 双模对话请求体 */
export interface AgentChatRequest {
  thread_id: string;
  message?: string;
  role: RoleType;
  action_payload?: AgentActionPayload;
}

/** A2UI 卡片类型 */
export type A2UICardType = 'APPROVAL_ACTION' | 'PERMIT_RESULT';

/** A2UI 结构化卡片 */
export interface A2UICard {
  card_type: A2UICardType;
  data: Record<string, unknown>;
}

/** 调度审核卡片（APPROVAL_ACTION）载荷结构 */
export interface ApprovalCardData {
  plan_id: string | null;
  voltage_level: string | null;
  audit_report: string | null;
  risk_level: string | null;
}

/** 调度许可结果卡片（PERMIT_RESULT）载荷结构 */
export interface PermitResultCardData {
  plan_id: string | null;
  permit_no: string | null;
  status: string | null;
}

/** SSE 流事件回调契约 */
export interface AgentStreamCallbacks {
  onToken: (content: string) => void;
  onCard: (card: A2UICard) => void;
  onError: (errorMsg: string) => void;
  onDone: () => void;
}

/** 服务端 SSE 扁平事件帧 */
interface ServerSSEEvent {
  type: 'token' | 'ui_card' | 'error' | 'done';
  content?: string;
  card_type?: A2UICardType;
  data?: Record<string, unknown>;
  message?: string;
}

/** 校验并收窄卡片类型（防御性编程：不信任服务端字段） */
function isValidCardType(value: unknown): value is A2UICardType {
  return value === 'APPROVAL_ACTION' || value === 'PERMIT_RESULT';
}

/**
 * A2UI 双模流式对话：POST /api/v1/agent/chat-stream
 *
 * 基于 @microsoft/fetch-event-source 处理事件分帧、TCP Buffer 拼接与重连控制；
 * 网络异常时不自动重试（POST 语义有状态，重放可能重复注入审批状态），统一上抛 onError。
 *
 * @param abortSignal 可选中断信号（切换会话/组件卸载时终止流）
 */
export async function streamChatAgent(
  request: AgentChatRequest,
  callbacks: AgentStreamCallbacks,
  abortSignal?: AbortSignal
): Promise<void> {
  let completed = false;

  try {
    await fetchEventSource(`${API_BASE_URL}${AGENT_CHAT_STREAM_PATH}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      // 页面切至后台时保持流式连接不断开
      openWhenHidden: true,
      signal: abortSignal,

      onopen: async (response) => {
        if (!response.ok) {
          throw new Error(`网关响应异常：HTTP ${response.status}`);
        }
        const contentType = response.headers.get('content-type') ?? '';
        if (!contentType.includes('text/event-stream')) {
          throw new Error(`网关返回非事件流：${contentType || '未知类型'}`);
        }
      },

      onmessage: (ev) => {
        if (completed || !ev.data) return;
        let parsed: ServerSSEEvent;
        try {
          parsed = JSON.parse(ev.data) as ServerSSEEvent;
        } catch {
          console.warn('[agent] 丢弃无法解析的 SSE 帧:', ev.data);
          return;
        }
        switch (parsed.type) {
          case 'token':
            if (typeof parsed.content === 'string' && parsed.content) {
              callbacks.onToken(parsed.content);
            }
            break;
          case 'ui_card':
            if (isValidCardType(parsed.card_type)) {
              callbacks.onCard({
                card_type: parsed.card_type,
                data: parsed.data ?? {},
              });
            }
            break;
          case 'error':
            callbacks.onError(parsed.message ?? '网关未返回错误详情');
            break;
          case 'done':
            completed = true;
            callbacks.onDone();
            break;
          default:
            console.warn('[agent] 未知的 SSE 事件类型:', parsed.type);
        }
      },

      // 网络层异常（断连/超时）直接上抛终止，交由调用方决定是否重新发起
      onerror: (err: unknown) => {
        throw err;
      },
    });

    // 兜底：服务端正常关流但未发 done 事件（防御性收口）
    if (!completed) {
      completed = true;
      callbacks.onDone();
    }
  } catch (err) {
    // 用户主动中断不算错误
    if (err instanceof DOMException && err.name === 'AbortError') return;
    const errorMsg = err instanceof Error ? err.message : String(err);
    if (!completed) callbacks.onError(errorMsg);
  }
}
