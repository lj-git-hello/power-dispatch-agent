<script setup lang="ts">
/**
 * WorkbenchLayout —— 通用三栏沉浸式工作台外壳。
 *
 * Header：标题 / SSE 状态灯 / 身份切换
 * 左栏：新建会话、视图 Tab、列表、本地存储运维
 * 中栏：当前会话标示、历史/审批视图、通用输入框
 * 右栏：折叠、业务表单 slot、Trace 面板
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Activity,
  ClipboardList,
  Plus,
  Trash2,
} from 'lucide-vue-next'

import TaskApprovalPool from './TaskApprovalPool.vue'
import TaskHistoryList from './TaskHistoryList.vue'
import type { TaskSummary } from '../a2ui/types'
import { chatStream, type StreamStatus } from '../api/agent'
import { http } from '../api/http'
import { useCurrentUser } from '../composables/useCurrentUser'
import { RenderTicker } from '../engine/render_ticker'
import { clearSession, loadMessages } from '../engine/storage'
import { PluginRegistry, type PluginIdentity } from '../plugins/registry'
import {
  type ApplyResult,
  useWorkbenchStore,
} from '../workbench/useWorkbenchStore'

// 通用工作台共享状态
const workbench = useWorkbenchStore()
const { state: workbenchState } = workbench
const { setCurrentUser } = useCurrentUser()

/** 插件未声明演示身份时的占位（不参与任何业务判定） */
const EMPTY_IDENTITY: PluginIdentity = {
  id: '',
  label: '未配置身份',
  role: '',
}

// ---- 当前身份（身份清单来自业务插件，底座不写死任何角色） ----
const identities = computed<PluginIdentity[]>(
  () => PluginRegistry.activeIdentities.value,
)
const identityId = ref<string>('')
const currentIdentity = computed<PluginIdentity>(
  () =>
    identities.value.find((item) => item.id === identityId.value) ??
    identities.value[0] ??
    EMPTY_IDENTITY,
)

// 调后端登录端点换取真实 JWT（后端只认合规 JWT，不能写 simulated:*）
async function loginAs(userId: string) {
  if (!userId) {
    return
  }
  const { data } = await http.post<{ access_token: string }>('/v1/auth/login', {
    user_id: userId,
  })
  localStorage.setItem('auth_token', data.access_token)
}

/** 已激活身份（避免重复登录；登录失败后清空以允许重试） */
let activatedId = ''

async function activateIdentity(userId: string): Promise<void> {
  if (!userId || userId === activatedId) {
    return
  }
  activatedId = userId
  try {
    await loginAs(userId)
    // 同步身份供深层卡片做权限判定
    setCurrentUser(userId, currentIdentity.value.role)
    // 切换身份后加载该用户的会话集合（审批人本地通常为空）
    await workbench.hydrateConversations(userId)
  } catch (error) {
    activatedId = ''
    console.error('身份激活失败：', error)
  }
}

async function switchIdentity(event: Event) {
  identityId.value = (event.target as HTMLSelectElement).value
}

// 身份清单由插件声明：清单到达后自动选中首个有效身份
watch(
  identities,
  (list) => {
    if (list.length && !list.some((item) => item.id === identityId.value)) {
      identityId.value = list[0].id
    }
  },
  { immediate: true, deep: true },
)

// 身份变化 → 重新登录并同步角色
watch(identityId, (userId) => {
  void activateIdentity(userId)
})

// ---- SSE 灯状态（由通用对话流的连接生命周期驱动） ----
// 注意：这盏灯反映的是"对话流"而非"网络连通性"——登录本身不建立流，
// 空闲期无流可查属于正常状态，不可用 Offline 这类断网措辞误导用户。
const sseStatus = ref<StreamStatus>('idle')
const sseMeta = {
  idle: { dot: 'bg-gray-400', text: 'Idle' },
  connected: { dot: 'bg-green-500', text: 'Connected' },
  reconnecting: { dot: 'bg-amber-500', text: 'Reconnecting' },
  offline: { dot: 'bg-red-500', text: 'Disconnected' },
} as const
/** 状态灯悬浮说明：明确它反映的是对话流，而非网络连通性 */
const sseStatusHint =
  '对话流（SSE）状态：Idle = 当前没有进行中的对话流，不代表后端离线'

// ---- 当前会话（ID 与消息由共享 store 持有） ----
function newSessionId(): string {
  return crypto.randomUUID()
}
// 初始化一个本地会话（延迟落库，不发请求）
workbench.setSession(newSessionId())
const sessionId = computed(() => workbenchState.activeSessionId)

const activeTab = ref<'history' | 'approval'>('history')
const draftText = ref('')
const storageHealthy = ref(true)

function createNewSession() {
  // 仅重置当前会话与中栏消息；严禁删除/覆盖会话集合中已有记录
  workbench.setSession(newSessionId())
  draftText.value = ''
  activeTab.value = 'history'
}

/** 点击会话项：切换到该会话并恢复其中栏消息。 */
async function selectConversation(summary: TaskSummary) {
  await workbench.openConversation(summary)
  activeTab.value = 'history'
}

/** 表单提交成功后的统一收口（供 App 经组件 ref 调用）。 */
function handleApplied(result: ApplyResult) {
  workbench.applyResult(result)
}

async function checkStorage() {
  try {
    await loadMessages(sessionId.value)
    storageHealthy.value = true
  } catch {
    storageHealthy.value = false
  }
}

async function wipeLocalSnapshot() {
  await clearSession(sessionId.value)
  storageHealthy.value = true
}

// 右栏开合由 store 统一持有（提交成功后自动折叠）
const rightOpen = computed(() => workbenchState.rightDrawerOpen)

// ---- 通用对话流（跨业务：端点与卡片协议均来自底座） ----
const isStreaming = ref(false)
const streamError = ref<string | null>(null)
let abortController: AbortController | null = null
let ticker: RenderTicker | null = null

/** 发送当前输入：走通用对话网关，token 经打字机逐字渲染。 */
async function sendDraft() {
  const text = draftText.value.trim()
  if (!text || isStreaming.value) {
    return
  }

  draftText.value = ''
  streamError.value = null

  const threadId = sessionId.value
  const createdAt = new Date().toISOString()

  // 用户消息立即入列
  workbench.appendMessage({
    id: crypto.randomUUID(),
    thread_id: threadId,
    role: 'user',
    kind: 'text',
    content: text,
    card_type: null,
    card_payload: null,
    retry_payload: null,
    created_at: createdAt,
  })

  // 助手占位消息：打字机逐字写入
  const answerId = crypto.randomUUID()
  workbench.appendMessage({
    id: answerId,
    thread_id: threadId,
    role: 'assistant',
    kind: 'text',
    content: '',
    card_type: null,
    card_payload: null,
    retry_payload: null,
    created_at: createdAt,
  })

  ticker?.clear()
  ticker = new RenderTicker((consumed) => {
    workbench.appendMessageText(answerId, consumed)
  })

  isStreaming.value = true
  abortController = new AbortController()

  try {
    await chatStream(
      { thread_id: threadId, session_id: threadId, message: text },
      {
        onToken: (content) => ticker?.enqueue(content),
        onCard: (cardType, data) => {
          workbench.appendMessage({
            id: crypto.randomUUID(),
            thread_id: threadId,
            role: 'assistant',
            kind: 'card',
            content: null,
            card_type: cardType,
            card_payload: { card_type: cardType, ...data },
            retry_payload: null,
            created_at: new Date().toISOString(),
          })
        },
        onError: (message) => {
          streamError.value = message
        },
        onDone: () => {
          // 立即排空打字机缓冲区，避免尾字滞留导致落盘内容不全
          ticker?.flush()
          ticker = null
          isStreaming.value = false
        },
        onStatus: (status) => {
          sseStatus.value = status
        },
      },
      abortController.signal,
    )
  } catch (error) {
    streamError.value =
      (error as { message?: string }).message ?? '对话连接失败，请稍后重试。'
  } finally {
    isStreaming.value = false
    abortController = null
  }
}

// 组件卸载时中止在途流，避免回调写入已销毁的状态
onBeforeUnmount(() => {
  abortController?.abort()
  ticker?.clear()
  ticker = null
})

// 暴露给装配层（App）调用
defineExpose({ handleApplied })

// 挂载时探测 IndexedDB 健康度
onMounted(async () => {
  // 启动时为当前身份确保一个有效 JWT（旧 simulated:* / 空值会被覆盖）
  await activateIdentity(currentIdentity.value.id)
  await checkStorage()
})
</script>

<template>
  <div class="flex h-full flex-col bg-white text-gray-800">
    <!-- Header -->
    <header class="flex h-14 shrink-0 items-center justify-between border-b bg-white px-4">
      <div class="flex items-center gap-2">
        <Activity class="h-5 w-5 text-blue-600" />
        <span class="text-sm font-semibold">企业级 AI Agent 应用平台</span>
      </div>

      <!-- SSE 状态灯 -->
      <div class="flex items-center gap-1.5">
        <span class="h-2 w-2 rounded-full" :class="sseMeta[sseStatus].dot" />
        <span class="text-xs text-gray-500" :title="sseStatusHint">
          {{ sseMeta[sseStatus].text }}
        </span>
      </div>

      <!-- 身份切换（身份清单来自业务插件） -->
      <select class="rounded-md border border-gray-300 px-2 py-1 text-xs disabled:opacity-50" :value="identityId"
        :disabled="identities.length === 0" @change="switchIdentity">
        <option v-for="item in identities" :key="item.id" :value="item.id">
          {{ item.label }} ({{ item.role }})
        </option>
      </select>
    </header>

    <!-- 主体三栏 -->
    <div class="flex flex-1 overflow-hidden">
      <!-- 左栏 -->
      <aside class="flex w-72 shrink-0 flex-col border-r bg-gray-50">
        <div class="p-3">
          <button type="button"
            class="flex w-full items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm text-white"
            @click="createNewSession">
            <Plus class="h-4 w-4" />
            新建会话
          </button>
        </div>

        <!-- Tab -->
        <div class="flex gap-1 px-3">
          <button type="button" class="rounded-md px-3 py-1 text-xs" :class="activeTab === 'history'
            ? 'bg-blue-100 text-blue-700'
            : 'text-gray-500 hover:bg-gray-100'
            " @click="activeTab = 'history'">
            我的会话
          </button>
          <button type="button" class="rounded-md px-3 py-1 text-xs" :class="activeTab === 'approval'
            ? 'bg-blue-100 text-blue-700'
            : 'text-gray-500 hover:bg-gray-100'
            " @click="activeTab = 'approval'">
            待办审批池
          </button>
        </div>

        <!-- 列表树：Tab1 渲染【我的会话】集合 -->
        <div class="flex-1 overflow-y-auto p-3">
          <template v-if="activeTab === 'history'">
            <p v-if="workbenchState.conversationList.length === 0" class="text-xs text-gray-400">
              暂无会话，可在右侧填报发起
            </p>

            <button v-for="item in workbenchState.conversationList" :key="item.thread_id" type="button"
              class="mb-2 w-full rounded-md border p-2 text-left transition hover:bg-white" :class="sessionId === item.session_id
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-200 bg-white'
                " @click="selectConversation(item)">
              <div class="flex items-center gap-1.5">
                <ClipboardList class="h-3.5 w-3.5 shrink-0 text-gray-400" />
                <span class="truncate text-xs font-medium text-gray-800">
                  {{ item.title ?? item.thread_id }}
                </span>
              </div>
              <div class="mt-1 flex items-center gap-1.5">
                <span class="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] text-amber-700">
                  {{ item.status }}
                </span>
                <span class="text-[10px] text-gray-500">
                  Lock: v{{ item.lock_version }}
                </span>
              </div>
            </button>
          </template>

          <!-- Tab2：待办审批池由中栏独立拉取，此处不渲染其数据 -->
          <p v-else class="text-xs text-gray-400">
            待办审批池见中栏
          </p>
        </div>

        <!-- 本地存储运维 -->
        <div class="border-t p-3">
          <p class="text-[10px] text-gray-500">
            IndexedDB：{{ storageHealthy ? '健康' : '异常' }}
          </p>
          <button type="button" class="mt-1 flex items-center gap-1 text-[10px] text-gray-500 hover:text-red-600"
            @click="wipeLocalSnapshot">
            <Trash2 class="h-3 w-3" />
            清空本地快照
          </button>
        </div>
      </aside>

      <!-- 中栏 -->
      <main class="flex flex-1 flex-col overflow-hidden bg-white">
        <div class="border-b px-4 py-2 text-xs text-gray-500">
          session_id: {{ sessionId }}
        </div>

        <div class="flex-1 overflow-hidden">
          <TaskHistoryList v-if="activeTab === 'history'" :session-id="sessionId" :current-user-id="currentIdentity.id"
            :messages="workbenchState.activeMessages" />
          <TaskApprovalPool v-else :current-user-id="currentIdentity.id" :current-role="currentIdentity.role" />
        </div>

        <!-- 通用输入 -->
        <div class="border-t p-3">
          <div class="flex items-center gap-2">
            <input v-model="draftText" type="text"
              class="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-50"
              placeholder="输入消息…" :disabled="isStreaming" @keyup.enter="sendDraft" />
            <button type="button" class="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              :disabled="isStreaming || !draftText.trim()" @click="sendDraft">
              {{ isStreaming ? '生成中…' : '发送' }}
            </button>
            <button type="button" class="rounded-md border border-gray-300 px-2 py-1.5 text-xs hover:bg-gray-50"
              title="展开右栏业务表单" @click="workbench.setRightDrawer(true)">
              📋 快速填报
            </button>
          </div>

          <!-- 流异常提示：明确反馈，不静默失败 -->
          <p v-if="streamError" class="mt-1.5 text-xs text-red-600">
            {{ streamError }}
          </p>
        </div>
      </main>

      <!-- 右栏 -->
      <!-- 折叠态保留 w-10 把手轨道：absolute 按钮需相对本 aside 定位，
           若容器宽度归零则把手仍会溢出视口外，导致右栏无法重新展开。 -->
      <aside class="relative flex flex-col border-l bg-gray-50/50 transition-all duration-300"
        :class="rightOpen ? 'w-80' : 'w-10'">
        <!-- v-show 而非 v-if：折叠时不销毁业务表单，已填数据得以保留 -->
        <div v-show="rightOpen" class="flex h-full flex-col">
          <div class="flex items-center justify-between p-3">
            <span class="text-xs font-medium">业务表单</span>
            <button type="button" class="text-xs text-gray-500" @click="workbench.setRightDrawer(false)">
              收起
            </button>
          </div>

          <div class="flex-1 overflow-y-auto p-3">
            <slot name="business-form" :session-id="sessionId">
              <p class="text-xs text-gray-400">
                业务插件表单位（后续挂载）
              </p>
            </slot>
          </div>

          <!-- Trace -->
          <div class="border-t p-3">
            <p class="mb-1 text-xs font-medium">运行追踪</p>
            <p class="text-[10px] text-gray-400">
              latency_ms / token 消耗（暂无数据）
            </p>
          </div>
        </div>

        <!-- 折叠态重新展开把手：相对 aside 定位（left-0），不再逃逸出 overflow-hidden -->
        <button v-if="!rightOpen" type="button"
          class="absolute left-0 top-2 z-10 h-8 w-6 rounded-l-md border border-r-0 border-gray-300 bg-white text-sm leading-none text-gray-500 shadow-sm hover:bg-gray-50 hover:text-gray-700"
          title="展开右栏" @click="workbench.setRightDrawer(true)">
          ›
        </button>
      </aside>
    </div>
  </div>
</template>
