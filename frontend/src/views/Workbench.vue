<template>
  <div class="workbench">
    <!-- ================= 左侧边栏 (280px)：角色 / 会话治理 ================= -->
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-badge">PD</span>
        <div class="brand-text">
          <span class="brand-title">电网检修调度协同工作台</span>
          <span class="brand-sub">A2UI · Generative UI Workspace</span>
        </div>
      </div>

      <!-- 角色切换器 -->
      <div class="role-switch">
        <label class="role-label">当前操作角色</label>
        <div class="role-options">
          <label
            class="role-option"
            :class="{ active: currentRole === 'APPLICANT' }"
          >
            <input
              v-model="currentRole"
              type="radio"
              name="role"
              value="APPLICANT"
              :disabled="streaming"
            />
            <span>👷 运检提报员</span>
          </label>
          <label
            class="role-option"
            :class="{ active: currentRole === 'DISPATCHER' }"
          >
            <input
              v-model="currentRole"
              type="radio"
              name="role"
              value="DISPATCHER"
              :disabled="streaming"
            />
            <span>⚡ 调度控制长</span>
          </label>
        </div>
      </div>

      <button class="btn-new-session" :disabled="streaming" @click="createSession">
        ＋ 发起新申报 / 问答
      </button>

      <!-- 会话历史列表 -->
      <div class="session-list">
        <div
          v-for="session in sessions"
          :key="session.thread_id"
          class="session-item"
          :class="{ active: session.thread_id === currentThreadId }"
          @click="switchSession(session.thread_id)"
        >
          <div class="session-main">
            <span class="session-thread">{{ session.thread_id }}</span>
            <span class="session-title">{{ session.title }}</span>
          </div>
          <div class="session-meta">
            <span
              class="status-tag"
              :class="`status-${session.status.toLowerCase()}`"
            >
              {{ SESSION_STATUS_LABELS[session.status] }}
            </span>
            <span class="session-time">{{ formatTime(session.updatedAt) }}</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- ================= 右侧主区：消息卡片流 + 输入控制台 ================= -->
    <main class="main-area">
      <!-- 顶部会话条 -->
      <header class="topbar">
        <div class="topbar-left">
          <span class="topbar-thread">{{ currentSession?.thread_id ?? '—' }}</span>
          <span
            v-if="currentSession"
            class="status-tag"
            :class="`status-${currentSession.status.toLowerCase()}`"
          >
            {{ SESSION_STATUS_LABELS[currentSession.status] }}
          </span>
        </div>
        <span class="topbar-role">
          当前角色：{{ currentRole === 'DISPATCHER' ? '调度控制长' : '运检提报员' }}
        </span>
      </header>

      <!-- 消息与卡片流 -->
      <section ref="streamRef" class="stream-area">
        <div v-if="currentMessages.length === 0" class="empty-state">
          <div class="empty-icon">⚡</div>
          <p>暂无会话内容</p>
          <p class="empty-hint">从下方快捷指令开始，或直接输入安规问题 / 检修申报</p>
        </div>

        <template v-for="message in currentMessages" :key="message.id">
          <!-- 用户气泡 -->
          <div v-if="message.role === 'user' && message.kind === 'text'" class="bubble-row user-row">
            <div class="bubble user-bubble">{{ message.content }}</div>
          </div>

          <!-- Agent 气泡（Markdown 流式渲染） -->
          <div
            v-else-if="message.role === 'agent' && message.kind === 'text'"
            class="bubble-row agent-row"
          >
            <div class="bubble agent-bubble">
              <div
                v-if="message.content"
                class="markdown-body"
                v-html="renderMarkdown(message.content)"
              ></div>
              <span
                v-if="streaming && message === streamingTail"
                class="typing-cursor"
              ></span>
              <div v-if="!message.content && streaming && message === streamingTail" class="typing-dots">
                <i></i><i></i><i></i>
              </div>
            </div>
          </div>

          <!-- A2UI 卡片：动态挂载于消息流 -->
          <div v-else-if="message.kind === 'card' && message.card" class="bubble-row agent-row">
            <template v-if="message.card.card_type === 'APPROVAL_ACTION'">
              <ApprovalActionCard
                :card-data="asApprovalCardData(message.card)"
                :current-role="currentRole"
                :locked="isApprovalLocked"
                @action="onApprovalAction"
              />
            </template>
            <template v-else-if="message.card.card_type === 'PERMIT_RESULT'">
              <PermitResultCard :card-data="asPermitResultCardData(message.card)" />
            </template>
          </div>
        </template>
      </section>

      <!-- ================= 输入控制台（吸底） ================= -->
      <footer class="console">
        <!-- 挂起等待审核提示条 -->
        <div v-if="awaitingApproval" class="pending-banner">
          <span class="pending-icon">⏸</span>
          本工单已触发高压熔断挂起，等待调度长核签——
          {{
            currentRole === 'DISPATCHER'
              ? '请在上方核签卡片执行【批准下达 / 驳回申请】'
              : '请切换为【调度控制长】角色，或等待调度长核签'
          }}
        </div>

        <!-- 快捷指令标签栏 -->
        <div class="quick-commands">
          <button
            v-for="cmd in QUICK_COMMANDS"
            :key="cmd"
            class="quick-chip"
            :disabled="streaming"
            @click="applyQuickCommand(cmd)"
          >
            {{ cmd }}
          </button>
        </div>

        <!-- 文本输入区 -->
        <div class="input-row">
          <textarea
            ref="inputRef"
            v-model="inputText"
            rows="2"
            placeholder="输入安规问题或检修申报内容...（Enter 发送，Shift+Enter 换行）"
            :disabled="streaming"
            @keydown="onKeydown"
          ></textarea>
          <button class="btn-send" :disabled="streaming || !inputText.trim()" @click="onSend">
            <span v-if="streaming" class="spinner"></span>
            {{ streaming ? '流转中' : '发送' }}
          </button>
        </div>
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import {
  useWorkbench,
  asApprovalCardData,
  asPermitResultCardData,
  SESSION_STATUS_LABELS,
  type ChatMessage,
} from '@/composables/useWorkbench';
import ApprovalActionCard from '@/components/cards/ApprovalActionCard.vue';
import PermitResultCard from '@/components/cards/PermitResultCard.vue';
import { renderMarkdown } from '@/utils/markdown';

/** 快捷指令标签（点击上屏） */
const QUICK_COMMANDS: readonly string[] = [
  '申报 110kV 舜耕站1号主变停电检修',
  '查询 220kV 设备不停电安全距离',
  '什么是两票三制？',
];

const {
  sessions,
  currentThreadId,
  currentRole,
  currentMessages,
  currentSession,
  streaming,
  awaitingApproval,
  createSession,
  switchSession,
  sendMessage,
  sendCardAction,
} = useWorkbench();

const inputText = ref('');
const streamRef = ref<HTMLElement | null>(null);
const inputRef = ref<HTMLTextAreaElement | null>(null);

/** 当前流式打字中的 Agent 消息（打字机光标定位） */
const streamingTail = computed<ChatMessage | null>(() => {
  if (!streaming.value) return null;
  const list = currentMessages.value;
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const msg = list[i];
    if (msg.role === 'agent' && msg.kind === 'text') return msg;
  }
  return null;
});

/** 核签卡片锁定：会话已办结或全局流式中不可再操作 */
const isApprovalLocked = computed<boolean>(
  () =>
    streaming.value ||
    (currentSession.value?.status === 'PERMITTED' || currentSession.value?.status === 'REJECTED')
);

/** 消息流变化时平滑滚动触底 */
function scrollToBottom(): void {
  nextTick(() => {
    const el = streamRef.value;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }).catch(() => {
    /* nextTick 中断可安全忽略 */
  });
}

watch(
  () => currentMessages.value[currentMessages.value.length - 1],
  () => scrollToBottom(),
  { deep: true }
);
watch(currentThreadId, () => {
  inputText.value = '';
  scrollToBottom();
});

/** Enter 发送 / Shift+Enter 换行 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    onSend();
  }
}

/** 快捷指令上屏并聚焦输入框 */
function applyQuickCommand(cmd: string): void {
  inputText.value = cmd;
  inputRef.value?.focus();
}

async function onSend(): Promise<void> {
  const text = inputText.value;
  if (!text.trim() || streaming.value) return;
  inputText.value = '';
  await sendMessage(text);
}

/** 调度长核签动作：组装 action_payload 唤醒状态机恢复 */
async function onApprovalAction(payload: { is_permitted: boolean; reason: string }): Promise<void> {
  await sendCardAction(payload);
}

/** 时间格式化（会话列表展示） */
function formatTime(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')} ${hh}:${mm}`;
}
</script>

<style scoped>
.workbench {
  display: flex;
  height: 100vh;
  overflow: hidden;
  font-family: var(--sans, system-ui, 'Segoe UI', sans-serif);
  background: var(--bg-app);
}

/* ==================== 左侧边栏 ==================== */
.sidebar {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, var(--bg-sidebar-start) 0%, var(--bg-sidebar-end) 100%);
  border-right: 1px solid var(--border-color);
  padding: 16px 14px;
  gap: 14px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-color);
}

.brand-badge {
  width: 38px;
  height: 38px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  color: #fff;
  font-weight: 800;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 1px;
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 1px;
}

.brand-sub {
  font-size: 10px;
  color: var(--text-secondary);
  letter-spacing: 1.2px;
  margin-top: 2px;
}

.role-switch {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.role-label {
  font-size: 11px;
  color: var(--text-secondary);
  letter-spacing: 1px;
}

.role-options {
  display: flex;
  gap: 8px;
}

.role-option {
  flex: 1;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 6px;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--bg-surface);
}

.role-option.active {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-soft);
  box-shadow: 0 0 0 1px var(--primary-ring);
}

.role-option input {
  display: none;
}

.btn-new-session {
  border: none;
  border-radius: 8px;
  padding: 11px 0;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.btn-new-session:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-new-session:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.session-item {
  border: 1px solid var(--border-color);
  border-radius: 9px;
  padding: 10px 12px;
  cursor: pointer;
  background: var(--bg-surface);
  transition: all 0.15s ease;
}

.session-item:hover {
  border-color: var(--border-strong);
}

.session-item.active {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.session-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-thread {
  font-family: var(--mono, monospace);
  font-size: 11px;
  color: var(--primary);
  letter-spacing: 0.5px;
}

.session-title {
  font-size: 12.5px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 7px;
}

.session-time {
  font-size: 10.5px;
  color: var(--text-secondary);
}

/* 状态标签（会话列表 + 顶栏共用） */
.status-tag {
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
  letter-spacing: 1px;
}

.status-qa {
  background: var(--status-qa-bg);
  color: var(--status-qa-text);
}

.status-waiting {
  background: var(--status-waiting-bg);
  color: var(--status-waiting-text);
}

.status-permitted {
  background: var(--status-permitted-bg);
  color: var(--status-permitted-text);
}

.status-rejected {
  background: var(--status-rejected-bg);
  color: var(--status-rejected-text);
}

/* ==================== 右侧主区 ==================== */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  height: 54px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-surface);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.topbar-thread {
  font-family: var(--mono, monospace);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.topbar-role {
  font-size: 12px;
  color: var(--text-secondary);
}

.stream-area {
  flex: 1;
  overflow-y: auto;
  padding: 22px 8%;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.empty-state {
  margin: auto;
  text-align: center;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 42px;
  margin-bottom: 10px;
}

.empty-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.bubble-row {
  display: flex;
}

.user-row {
  justify-content: flex-end;
}

.agent-row {
  justify-content: flex-start;
}

.bubble {
  max-width: 78%;
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 13.5px;
  line-height: 1.7;
  word-break: break-word;
}

.user-bubble {
  background: linear-gradient(135deg, var(--primary-dark), var(--primary));
  color: #f0f9ff;
  border-bottom-right-radius: 3px;
  white-space: pre-wrap;
}

.agent-bubble {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  border-bottom-left-radius: 3px;
  position: relative;
}

/* Markdown 流式渲染样式 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5) {
  margin: 12px 0 6px;
  color: var(--text-primary);
  font-size: 15px;
  line-height: 1.4;
}

.markdown-body :deep(h1) {
  font-size: 17px;
}

.markdown-body :deep(p) {
  margin: 6px 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 6px 0;
  padding-left: 22px;
}

.markdown-body :deep(li) {
  margin: 3px 0;
}

.markdown-body :deep(li::marker) {
  color: var(--primary);
}

.markdown-body :deep(strong) {
  color: var(--text-primary);
  font-weight: 700;
}

.markdown-body :deep(a) {
  color: var(--primary);
  text-decoration: none;
}

.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(blockquote) {
  margin: 8px 0;
  padding: 6px 12px;
  border-left: 3px solid var(--primary);
  background: var(--primary-soft);
  color: var(--text-secondary);
  border-radius: 0 6px 6px 0;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 12.5px;
  display: block;
  overflow-x: auto;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--border-color);
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: var(--bg-subtle);
  font-weight: 700;
  color: var(--text-primary);
}

.markdown-body :deep(code) {
  background: var(--code-bg);
  color: var(--primary-dark);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12.5px;
  font-family: var(--mono, monospace);
}

.markdown-body :deep(pre) {
  background: var(--code-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 8px 0;
}

.markdown-body :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
  color: var(--text-primary);
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px dashed var(--border-strong);
  margin: 10px 0;
}

/* 打字机光标 */
.typing-cursor {
  display: inline-block;
  width: 7px;
  height: 15px;
  background: var(--primary);
  margin-left: 2px;
  vertical-align: -2px;
  animation: blink 0.9s step-end infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* 等待回复三点动画 */
.typing-dots {
  display: flex;
  gap: 5px;
  padding: 4px 0;
}

.typing-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: bounce 1.2s infinite ease-in-out;
}

.typing-dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-dots i:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  40% {
    transform: translateY(-5px);
    opacity: 1;
  }
}

/* ==================== 输入控制台 ==================== */
.console {
  flex-shrink: 0;
  border-top: 1px solid var(--border-color);
  background: var(--bg-surface);
  padding: 12px 8% 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pending-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--status-waiting-bg);
  border: 1px solid var(--status-waiting-border);
  color: var(--status-waiting-text);
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 12.5px;
}

.quick-commands {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.quick-chip {
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--primary);
  font-size: 12px;
  border-radius: 999px;
  padding: 5px 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.quick-chip:hover:not(:disabled) {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.quick-chip:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: stretch;
}

.input-row textarea {
  flex: 1;
  resize: none;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  color: var(--text-primary);
  font-size: 13.5px;
  line-height: 1.6;
  padding: 10px 14px;
  font-family: inherit;
  box-sizing: border-box;
}

.input-row textarea::placeholder {
  color: var(--text-muted);
}

.input-row textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-ring);
}

.input-row textarea:disabled {
  opacity: 0.55;
}

.btn-send {
  width: 92px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  color: #fff;
  font-size: 13.5px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  transition: opacity 0.15s ease;
}

.btn-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 流式 Loading 转圈 */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
