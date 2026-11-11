<script setup lang="ts">
/**
 * WorkbenchLayout —— 通用三栏沉浸式工作台外壳。
 *
 * Header：标题 / SSE 状态灯 / 身份切换
 * 左栏：新建会话、视图 Tab、列表、本地存储运维
 * 中栏：当前会话标示、历史/审批视图、通用输入框
 * 右栏：折叠、业务表单 slot、Trace 面板
 */
import { computed, onMounted, ref } from 'vue'
import {
  Activity,
  ClipboardList,
  Plus,
  Trash2,
} from 'lucide-vue-next'

import TaskApprovalPool from './TaskApprovalPool.vue'
import TaskHistoryList from './TaskHistoryList.vue'
import type {
  TaskSummary,
  WorkflowEndpoints,
} from '../a2ui/types'
import { http } from '../api/http'
import { useCurrentUser } from '../composables/useCurrentUser'
import { clearSession, loadMessages } from '../engine/storage'
import {
  type ApplyResult,
  useWorkbenchStore,
} from '../workbench/useWorkbenchStore'

// 端点配置由业务插件经宿主注入；缺省时子视图使用各自通用占位路径
const props = defineProps<{
  endpoints?: WorkflowEndpoints
}>()

// 通用工作台共享状态
const workbench = useWorkbenchStore()
const { state: workbenchState } = workbench
const { setCurrentUser } = useCurrentUser()

type IdentityId = 'applicant_01' | 'dispatcher_lead'
interface Identity {
  id: IdentityId
  label: string
  role: 'APPLICANT' | 'DISPATCHER'
}

const IDENTITIES: Identity[] = [
  { id: 'applicant_01', label: '张三 (APPLICANT)', role: 'APPLICANT' },
  { id: 'dispatcher_lead', label: '李审批长 (DISPATCHER)', role: 'DISPATCHER' },
]

// ---- 当前身份 ----
const identityId = ref<IdentityId>('applicant_01')
const currentIdentity = computed(
  () => IDENTITIES.find((item) => item.id === identityId.value)!,
)

// 调后端登录端点换取真实 JWT（后端只认合规 JWT，不能写 simulated:*）
async function loginAs(userId: IdentityId) {
  const { data } = await http.post<{ access_token: string }>('/v1/auth/login', {
    user_id: userId,
  })
  localStorage.setItem('auth_token', data.access_token)
}

async function switchIdentity(event: Event) {
  identityId.value = (event.target as HTMLSelectElement).value as IdentityId
  try {
    await loginAs(identityId.value)
    // 同步身份供深层卡片做权限判定
    setCurrentUser(identityId.value, currentIdentity.value.role)
    // 切换身份后加载该用户的会话集合（审批人本地通常为空）
    await workbench.hydrateConversations(identityId.value)
  } catch (error) {
    console.error('身份切换失败：', error)
  }
}

// ---- SSE 灯状态（默认离线；实际由后续接入的 SSEClient onStatus 更新） ----
const sseStatus = ref<'connected' | 'reconnecting' | 'offline'>('offline')
const sseMeta = {
  connected: { dot: 'bg-green-500', text: 'Connected' },
  reconnecting: { dot: 'bg-amber-500', text: 'Reconnecting' },
  offline: { dot: 'bg-gray-400', text: 'Offline' },
} as const

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

function sendDraft() {
  // 本步仅占位：通用发送逻辑后续接入
  draftText.value = ''
}

// 暴露给装配层（App）调用
defineExpose({ handleApplied })

// 挂载时探测 IndexedDB 健康度
onMounted(async () => {
  // 启动时为当前身份确保一个有效 JWT（旧 simulated:* / 空值会被覆盖）
  await loginAs(identityId.value).catch((error) =>
    console.error('启动登录失败：', error),
  )
  setCurrentUser(identityId.value, currentIdentity.value.role)
  await workbench.hydrateConversations(identityId.value)
  await checkStorage()
})
</script>

<template>
  <div class="flex h-screen flex-col bg-white text-gray-800">
    <!-- Header -->
    <header
      class="flex h-14 shrink-0 items-center justify-between border-b bg-white px-4"
    >
      <div class="flex items-center gap-2">
        <Activity class="h-5 w-5 text-blue-600" />
        <span class="text-sm font-semibold">Universal Agent Workbench</span>
      </div>

      <!-- SSE 状态灯 -->
      <div class="flex items-center gap-1.5">
        <span
          class="h-2 w-2 rounded-full"
          :class="sseMeta[sseStatus].dot"
        />
        <span class="text-xs text-gray-500">
          {{ sseMeta[sseStatus].text }}
        </span>
      </div>

      <!-- 身份切换 -->
      <select
        class="rounded-md border border-gray-300 px-2 py-1 text-xs"
        :value="identityId"
        @change="switchIdentity"
      >
        <option v-for="item in IDENTITIES" :key="item.id" :value="item.id">
          {{ item.label }}
        </option>
      </select>
    </header>

    <!-- 主体三栏 -->
    <div class="flex flex-1 overflow-hidden">
      <!-- 左栏 -->
      <aside class="flex w-72 shrink-0 flex-col border-r bg-gray-50">
        <div class="p-3">
          <button
            type="button"
            class="flex w-full items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm text-white"
            @click="createNewSession"
          >
            <Plus class="h-4 w-4" />
            新建会话
          </button>
        </div>

        <!-- Tab -->
        <div class="flex gap-1 px-3">
          <button
            type="button"
            class="rounded-md px-3 py-1 text-xs"
            :class="
              activeTab === 'history'
                ? 'bg-blue-100 text-blue-700'
                : 'text-gray-500 hover:bg-gray-100'
            "
            @click="activeTab = 'history'"
          >
            我的会话
          </button>
          <button
            type="button"
            class="rounded-md px-3 py-1 text-xs"
            :class="
              activeTab === 'approval'
                ? 'bg-blue-100 text-blue-700'
                : 'text-gray-500 hover:bg-gray-100'
            "
            @click="activeTab = 'approval'"
          >
            待办审批池
          </button>
        </div>

        <!-- 列表树：Tab1 渲染【我的会话】集合 -->
        <div class="flex-1 overflow-y-auto p-3">
          <template v-if="activeTab === 'history'">
            <p
              v-if="workbenchState.conversationList.length === 0"
              class="text-xs text-gray-400"
            >
              暂无会话，可在右侧填报发起
            </p>

            <button
              v-for="item in workbenchState.conversationList"
              :key="item.thread_id"
              type="button"
              class="mb-2 w-full rounded-md border p-2 text-left transition hover:bg-white"
              :class="
                sessionId === item.session_id
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 bg-white'
              "
              @click="selectConversation(item)"
            >
              <div class="flex items-center gap-1.5">
                <ClipboardList class="h-3.5 w-3.5 shrink-0 text-gray-400" />
                <span class="truncate text-xs font-medium text-gray-800">
                  {{ item.title ?? item.thread_id }}
                </span>
              </div>
              <div class="mt-1 flex items-center gap-1.5">
                <span
                  class="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] text-amber-700"
                >
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
          <button
            type="button"
            class="mt-1 flex items-center gap-1 text-[10px] text-gray-500 hover:text-red-600"
            @click="wipeLocalSnapshot"
          >
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
          <TaskHistoryList
            v-if="activeTab === 'history'"
            :session-id="sessionId"
            :current-user-id="currentIdentity.id"
            :messages="workbenchState.activeMessages"
          />
          <TaskApprovalPool
            v-else
            :current-user-id="currentIdentity.id"
            :current-role="currentIdentity.role"
            :endpoints="props.endpoints"
          />
        </div>

        <!-- 通用输入 -->
        <div class="border-t p-3">
          <div class="flex items-center gap-2">
            <input
              v-model="draftText"
              type="text"
              class="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
              placeholder="输入消息…"
              @keyup.enter="sendDraft"
            />
            <button
              type="button"
              class="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white"
              @click="sendDraft"
            >
              发送
            </button>
            <button
              type="button"
              class="rounded-md border border-gray-300 px-2 py-1.5 text-xs"
            >
              📋 快速填报
            </button>
          </div>
        </div>
      </main>

      <!-- 右栏 -->
      <aside
        class="flex flex-col border-l bg-gray-50/50 transition-all duration-300"
        :class="rightOpen ? 'w-80' : 'w-0'"
      >
        <div v-if="rightOpen" class="flex h-full flex-col">
          <div class="flex items-center justify-between p-3">
            <span class="text-xs font-medium">业务表单</span>
            <button
              type="button"
              class="text-xs text-gray-500"
              @click="workbench.setRightDrawer(false)"
            >
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

        <!-- 折叠态重新展开 -->
        <button
          v-if="!rightOpen"
          type="button"
          class="absolute"
          @click="workbench.setRightDrawer(true)"
        >
          ›
        </button>
      </aside>
    </div>
  </div>
</template>
