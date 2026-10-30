import { computed, ref, watch } from 'vue';
import {
  streamChatAgent,
  type A2UICard,
  type AgentChatRequest,
  type ApprovalCardData,
  type PermitResultCardData,
  type RoleType,
} from '@/api/agent';

// ============================================================
// 工作台领域模型（严格类型，禁止 any）
// ============================================================

/** 会话业务状态 */
export type SessionStatus = 'QA' | 'WAITING' | 'PERMITTED' | 'REJECTED';

/** 消息发送方 */
export type MessageRole = 'user' | 'agent';

/** 流式消息条目：文本气泡 或 挂载的 A2UI 卡片 */
export interface ChatMessage {
  id: string;
  role: MessageRole;
  kind: 'text' | 'card';
  /** 文本气泡内容（kind === 'text'） */
  content: string;
  /** 挂载卡片（kind === 'card'） */
  card?: A2UICard;
}

/** 会话档案 */
export interface SessionInfo {
  thread_id: string;
  title: string;
  status: SessionStatus;
  updatedAt: number;
}

/** localStorage 持久化档案（含全部消息） */
interface SessionArchive {
  sessions: SessionInfo[];
  messages: Record<string, ChatMessage[]>;
}

/** 会话状态标签文案映射（禁止魔法值散落） */
export const SESSION_STATUS_LABELS: Record<SessionStatus, string> = {
  QA: '问答',
  WAITING: '待审核',
  PERMITTED: '已许可',
  REJECTED: '已驳回',
};

const STORAGE_KEY = 'power_dispatch_workbench_v1';

function generateMessageId(): string {
  return `msg_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function createThreadId(): string {
  return `PLAN_${Date.now().toString().slice(-6)}`;
}

/** 依据首条用户消息生成会话标题 */
function deriveTitle(text: string): string {
  const clean = text.trim().replace(/\s+/g, ' ');
  return clean.length > 18 ? `${clean.slice(0, 18)}…` : clean || '新会话';
}

function loadArchive(): SessionArchive {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { sessions: [], messages: {} };
    const parsed = JSON.parse(raw) as Partial<SessionArchive>;
    return {
      sessions: Array.isArray(parsed.sessions) ? parsed.sessions : [],
      messages: parsed.messages && typeof parsed.messages === 'object' ? parsed.messages : {},
    };
  } catch {
    return { sessions: [], messages: {} };
  }
}

// ============================================================
// 模块级响应式单例：全局下发角色与会话状态
// ============================================================
const archive = loadArchive();

const sessions = ref<SessionInfo[]>(archive.sessions);
/** thread_id -> 消息流 */
const messagesMap = ref<Record<string, ChatMessage[]>>(archive.messages);
const currentThreadId = ref<string>('');
const currentRole = ref<RoleType>('APPLICANT');
const streaming = ref(false);
/** 当前是否有流式错误待展示 */
const lastError = ref('');

if (sessions.value.length === 0) {
  createSession();
} else {
  currentThreadId.value = sessions.value[0].thread_id;
}

// 会话数据变更即落盘（刷新不丢失协同上下文）
watch(
  [sessions, messagesMap],
  () => {
    try {
      const payload: SessionArchive = {
        sessions: sessions.value,
        messages: messagesMap.value,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch (err) {
      console.warn('[workbench] 会话存档写入失败:', err);
    }
  },
  { deep: true }
);

const currentMessages = computed<ChatMessage[]>(
  () => messagesMap.value[currentThreadId.value] ?? []
);

const currentSession = computed<SessionInfo | null>(
  () => sessions.value.find((s) => s.thread_id === currentThreadId.value) ?? null
);

/** 当前会话是否挂起等待调度长核签 */
const awaitingApproval = computed<boolean>(() => currentSession.value?.status === 'WAITING');

function touchSession(threadId: string): void {
  const session = sessions.value.find((s) => s.thread_id === threadId);
  if (session) {
    session.updatedAt = Date.now();
    // 触发排序视图：置顶当前活跃会话
    sessions.value = [...sessions.value];
  }
}

function setSessionStatus(threadId: string, status: SessionStatus): void {
  const session = sessions.value.find((s) => s.thread_id === threadId);
  if (session && session.status !== 'PERMITTED' && session.status !== 'REJECTED') {
    // 终态不可逆：已签发/已驳回的工单不被后续问答覆盖业务状态
    session.status = status;
    sessions.value = [...sessions.value];
  }
}

function appendMessage(threadId: string, message: ChatMessage): void {
  messagesMap.value[threadId] = [...(messagesMap.value[threadId] ?? []), message];
  touchSession(threadId);
}

/** 新建会话并切换为当前会话 */
function createSession(): void {
  const threadId = createThreadId();
  sessions.value = [
    { thread_id: threadId, title: '新会话', status: 'QA', updatedAt: Date.now() },
    ...sessions.value,
  ];
  messagesMap.value[threadId] = [];
  currentThreadId.value = threadId;
}

/** 切换会话 */
function switchSession(threadId: string): void {
  if (streaming.value) return; // 流式执行中禁止切换，防止状态错乱
  currentThreadId.value = threadId;
}

/** 依据卡片事件驱动会话业务状态 */
function applyCardToSession(threadId: string, card: A2UICard): void {
  if (card.card_type === 'APPROVAL_ACTION') {
    setSessionStatus(threadId, 'WAITING');
  } else if (card.card_type === 'PERMIT_RESULT') {
    const status = String(card.data.status ?? '');
    if (status === 'PERMITTED') setSessionStatus(threadId, 'PERMITTED');
    else if (status === 'REJECTED') setSessionStatus(threadId, 'REJECTED');
  }
}

/**
 * 发起 A2UI 双模流式请求（对话与卡片动作统一入口）
 */
async function dispatchStream(request: AgentChatRequest, agentMessageId: string): Promise<void> {
  streaming.value = true;
  lastError.value = '';
  try {
    await streamChatAgent(request, {
      onToken: (content) => {
        const list = messagesMap.value[request.thread_id] ?? [];
        const idx = list.findIndex((m) => m.id === agentMessageId);
        if (idx >= 0) {
          const next = [...list];
          next[idx] = { ...next[idx], content: next[idx].content + content };
          messagesMap.value[request.thread_id] = next;
        }
      },
      onCard: (card) => {
        applyCardToSession(request.thread_id, card);
        appendMessage(request.thread_id, {
          id: generateMessageId(),
          role: 'agent',
          kind: 'card',
          content: '',
          card,
        });
      },
      onError: (errorMsg) => {
        lastError.value = errorMsg;
        appendMessage(request.thread_id, {
          id: generateMessageId(),
          role: 'agent',
          kind: 'text',
          content: `【网关异常】${errorMsg}`,
        });
      },
      onDone: () => {
        /* 收口由 streaming 状态复位处理 */
      },
    });
  } finally {
    streaming.value = false;
    touchSession(request.thread_id);
  }
}

/** 发送普通对话/申报消息 */
async function sendMessage(text: string): Promise<void> {
  const content = text.trim();
  if (!content || streaming.value) return;

  const threadId = currentThreadId.value;
  const isFirstMessage = (messagesMap.value[threadId] ?? []).length === 0;
  if (isFirstMessage) {
    const session = sessions.value.find((s) => s.thread_id === threadId);
    if (session) session.title = deriveTitle(content);
  }

  appendMessage(threadId, {
    id: generateMessageId(),
    role: 'user',
    kind: 'text',
    content,
  });

  const agentMessageId = generateMessageId();
  appendMessage(threadId, {
    id: agentMessageId,
    role: 'agent',
    kind: 'text',
    content: '',
  });

  await dispatchStream(
    { thread_id: threadId, message: content, role: currentRole.value },
    agentMessageId
  );
}

/** 调度长卡片核签：唤醒状态机断点恢复 */
async function sendCardAction(payload: { is_permitted: boolean; reason: string }): Promise<void> {
  if (streaming.value) return;
  const threadId = currentThreadId.value;

  const agentMessageId = generateMessageId();
  appendMessage(threadId, {
    id: agentMessageId,
    role: 'agent',
    kind: 'text',
    content: '',
  });

  await dispatchStream(
    {
      thread_id: threadId,
      role: currentRole.value,
      action_payload: {
        is_permitted: payload.is_permitted,
        reason: payload.reason || undefined,
      },
    },
    agentMessageId
  );
}

/** 卡片载荷收窄工具：供视图层使用 */
export function asApprovalCardData(card: A2UICard): ApprovalCardData {
  const data = card.data;
  return {
    plan_id: typeof data.plan_id === 'string' ? data.plan_id : null,
    voltage_level: typeof data.voltage_level === 'string' ? data.voltage_level : null,
    audit_report: typeof data.audit_report === 'string' ? data.audit_report : null,
    risk_level: typeof data.risk_level === 'string' ? data.risk_level : null,
  };
}

export function asPermitResultCardData(card: A2UICard): PermitResultCardData {
  const data = card.data;
  return {
    plan_id: typeof data.plan_id === 'string' ? data.plan_id : null,
    permit_no: typeof data.permit_no === 'string' ? data.permit_no : null,
    status: typeof data.status === 'string' ? data.status : null,
  };
}

export function useWorkbench() {
  return {
    sessions,
    currentThreadId,
    currentRole,
    currentMessages,
    currentSession,
    streaming,
    lastError,
    awaitingApproval,
    createSession,
    switchSession,
    sendMessage,
    sendCardAction,
  };
}
