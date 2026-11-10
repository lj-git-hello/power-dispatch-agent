<script setup lang="ts">
/**
 * TaskApprovalPool —— 通用待办审批看板。
 *
 * 拉取 WAITING_HUMAN 且 assigned_role 匹配的任务；展示锁版本徽章，
 * 点击展开详情（卡片经 MessageCardHost）；核准/驳回走 useWorkflowAction，
 * 409 冲突时自动刷新剔除脏任务。
 */
import { computed, onMounted, ref } from 'vue'

import MessageCardHost from '../a2ui/MessageCardHost.vue'
import type {
  CardActionContext,
  ChatMessageRecord,
  ResumeActionContext,
  TaskSummary,
  WorkflowEndpoints,
} from '../a2ui/types'
import { http } from '../api/http'
import { useWorkflowAction } from '../composables/useWorkflowAction'

const props = defineProps<{
  currentUserId: string
  currentRole: string
  /** 端点配置：由业务插件注入，缺省用通用占位路径 */
  endpoints?: WorkflowEndpoints
}>()

// 缺省端点（core 不写死任何业务路径）
const FALLBACK_ENDPOINTS: WorkflowEndpoints = {
  tasks: '/v1/workflow/tasks',
  messages: '/v1/workflow/messages',
  resume: '/v1/workflow/resume',
}
const endpoints = computed<WorkflowEndpoints>(
  () => props.endpoints ?? FALLBACK_ENDPOINTS,
)

const tasks = ref<TaskSummary[]>([])
const selectedThreadId = ref<string | null>(null)
const detailMessages = ref<ChatMessageRecord[]>([])

const { isSubmitting, resumeWorkflow, notice } = useWorkflowAction()

async function fetchTasks() {
  // 通用待办端点（业务无关，按角色过滤）
  const { data } = await http.get<{ items: TaskSummary[] }>(
    endpoints.value.tasks,
    { params: { assigned_role: props.currentRole } },
  )
  tasks.value = (data.items ?? []).filter(
    (task) =>
      task.status === 'WAITING_HUMAN' &&
      task.assigned_role === props.currentRole,
  )
}

async function openDetail(task: TaskSummary) {
  selectedThreadId.value = task.thread_id
  const { data } = await http.get<{ items: ChatMessageRecord[] }>(
    endpoints.value.messages,
    { params: { thread_id: task.thread_id } },
  )
  detailMessages.value = data.items ?? []
}

function makeResumeContext(
  task: TaskSummary,
  approved: boolean,
): ResumeActionContext {
  return {
    thread_id: task.thread_id,
    lock_version: task.lock_version,
    action: approved ? 'approve' : 'reject',
    payload: null,
  }
}

async function decide(task: TaskSummary, approved: boolean) {
  await resumeWorkflow(
    endpoints.value.resume,
    makeResumeContext(task, approved),
    // 成功：刷新待办与详情
    async () => {
      await fetchTasks()
      if (selectedThreadId.value === task.thread_id) {
        selectedThreadId.value = null
        detailMessages.value = []
      }
    },
    // 409 冲突：任务已被处理，刷新剔除
    async () => {
      await fetchTasks()
      detailMessages.value = []
      if (selectedThreadId.value === task.thread_id) {
        selectedThreadId.value = null
      }
    },
  )
}

function makeActionContext(message: ChatMessageRecord): CardActionContext {
  return {
    threadId: message.thread_id,
    retryPayload: message.retry_payload,
    dispatch: () => undefined,
  }
}

onMounted(fetchTasks)

defineExpose({ refresh: fetchTasks })
</script>

<template>
  <div class="flex h-full overflow-hidden">
    <!-- 待办列表 -->
    <div class="w-64 shrink-0 overflow-y-auto border-r border-gray-200 p-3">
      <p v-if="tasks.length === 0" class="text-sm text-gray-400">
        暂无待办任务
      </p>

      <button
        v-for="task in tasks"
        :key="task.thread_id"
        type="button"
        class="mb-2 w-full rounded-md border p-2 text-left transition hover:bg-gray-50"
        :class="
          selectedThreadId === task.thread_id
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-200'
        "
        @click="openDetail(task)"
      >
        <p class="truncate text-xs font-medium text-gray-800">
          {{ task.thread_id }}
        </p>
        <div class="mt-1 flex items-center gap-2">
          <span
            class="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] text-amber-700">{{ task.status }}</span>
          <span class="text-[10px] text-gray-500">
            Lock: v{{ task.lock_version }}
          </span>
        </div>
      </button>
    </div>

    <!-- 详情主区 -->
    <div class="flex flex-1 flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-4">
        <p v-if="!selectedThreadId" class="text-sm text-gray-400">
          请选择左侧待办查看详情
        </p>

        <div
          v-for="message in detailMessages"
          :key="message.id"
          class="mb-3"
        >
          <MessageCardHost
            v-if="message.kind === 'card'"
            :message="message"
            :action-context="makeActionContext(message)"
          />
          <p v-else class="text-sm text-gray-700">{{ message.content }}</p>
        </div>
      </div>

      <!-- 核准 / 驳回 -->
      <div
        v-if="selectedThreadId"
        class="flex items-center gap-2 border-t border-gray-200 p-3"
      >
        <button
          type="button"
          class="rounded-md bg-green-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          :disabled="isSubmitting"
          @click="
            decide(
              tasks.find((t) => t.thread_id === selectedThreadId)!,
              true,
            )
          "
        >
          核准
        </button>
        <button
          type="button"
          class="rounded-md bg-gray-200 px-3 py-1.5 text-sm text-gray-700 disabled:opacity-50"
          :disabled="isSubmitting"
          @click="
            decide(
              tasks.find((t) => t.thread_id === selectedThreadId)!,
              false,
            )
          "
        >
          驳回
        </button>
        <p v-if="notice" class="text-xs text-amber-600">
          {{ notice.message }}
        </p>
      </div>
    </div>
  </div>
</template>
