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
  TaskSummary,
} from '../a2ui/types'
import { http } from '../api/http'
import { useWorkflowAction } from '../composables/useWorkflowAction'
import { PluginRegistry } from '../plugins/registry'

const props = defineProps<{
  currentUserId: string
  currentRole: string
}>()

// 端点由插件注册表下发（后端 manifest 为唯一真相源）；core 不写死任何业务路径
const endpoints = computed(() => PluginRegistry.activeEndpoints.value)

/** 端点缺失（插件未注册 / 清单未同步）时的显式配置错误 */
const configError = ref<string | null>(null)

const tasks = ref<TaskSummary[]>([])
const selectedThreadId = ref<string | null>(null)
const detailMessages = ref<ChatMessageRecord[]>([])

const { isSubmitting, submitAudit, notice } = useWorkflowAction()

let loaded = false

async function fetchTasks(force = false) {
  const tasksUrl = endpoints.value?.tasks
  if (!tasksUrl) {
    configError.value =
      '工作流端点未配置：业务插件未注册或后端清单未同步，请检查插件装载状态。'
    return
  }
  configError.value = null

  // 角色由后端按 JWT 判定，前端不传任何角色参数
  const { data } = await http.get<{ items: TaskSummary[] }>(tasksUrl)
  tasks.value = data.items ?? []
  loaded = true
  void force
}

/** Tab 激活时调用：首次进入懒加载，重复进入不重复请求。 */
async function activate() {
  if (!loaded) await fetchTasks()
}

async function openDetail(task: TaskSummary) {
  const messagesUrl = endpoints.value?.messages
  if (!messagesUrl) {
    configError.value =
      '工作流端点未配置：业务插件未注册或后端清单未同步，请检查插件装载状态。'
    return
  }
  selectedThreadId.value = task.thread_id
  const { data } = await http.get<{ items: ChatMessageRecord[] }>(
    messagesUrl,
    { params: { thread_id: task.thread_id } },
  )
  detailMessages.value = data.items ?? []
}

async function decide(task: TaskSummary, approved: boolean) {
  const resumeUrl = endpoints.value?.resume
  if (!resumeUrl) {
    configError.value =
      '工作流端点未配置：业务插件未注册或后端清单未同步，请检查插件装载状态。'
    return
  }
  await submitAudit(
    resumeUrl,
    {
      thread_id: task.thread_id,
      lock_version: task.lock_version,
      approved,
      opinion: approved ? '核准许可' : '驳回修改',
    },
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

// 组件仅在切到审批池 Tab 时挂载，挂载即懒加载（首次点击才发请求）
onMounted(activate)

defineExpose({ refresh: fetchTasks, activate })
</script>

<template>
  <div class="flex h-full overflow-hidden">
    <!-- 待办列表 -->
    <div class="w-64 shrink-0 overflow-y-auto border-r border-gray-200 p-3">
      <p
        v-if="configError"
        class="mb-2 rounded-md bg-red-50 p-2 text-xs text-red-600"
      >
        {{ configError }}
      </p>

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
