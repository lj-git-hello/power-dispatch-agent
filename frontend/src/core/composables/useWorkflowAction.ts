/**
 * useWorkflowAction —— 通用工作流动作调度（CAS 乐观锁恢复）。
 *
 * 维护提交/错误状态；POST 体严格按 CAS 规范包含 thread_id/lock_version/action/payload；
 * 捕获 409 冲突时触发 onConflict 回调与轻量通知。
 */

import { AxiosError } from 'axios'
import { ref } from 'vue'

import type { ResumeActionContext } from '../a2ui/types'
import { http, type ApiError } from '../api/http'

/** 轻量通知结构（调用方可对接 Toast UI） */
export interface ActionNotice {
  type: 'conflict' | 'error'
  message: string
}

export function useWorkflowAction() {
  const isSubmitting = ref(false)
  const errorMessage = ref<string | null>(null)
  const notice = ref<ActionNotice | null>(null)

  /** 从归一化错误或原始 AxiosError 中提取状态码与详情。 */
  function readError(error: unknown): { status: number; detail: string } {
    if (error instanceof AxiosError) {
      return {
        status: error.response?.status ?? 0,
        detail: (error.response?.data as { detail?: string } | undefined)?.detail
          ?? error.message,
      }
    }
    const apiError = error as ApiError
    return { status: apiError.status, detail: apiError.message }
  }

  async function resumeWorkflow(
    url: string,
    context: ResumeActionContext,
    onSuccess?: (data: unknown) => void,
    onConflict?: (detail: string) => void,
  ): Promise<void> {
    isSubmitting.value = true
    errorMessage.value = null
    notice.value = null

    try {
      const { data } = await http.post(url, {
        thread_id: context.thread_id,
        lock_version: context.lock_version,
        action: context.action,
        payload: context.payload,
      })
      onSuccess?.(data)
    } catch (error) {
      const { status, detail } = readError(error)
      if (status === 409) {
        notice.value = { type: 'conflict', message: detail }
        onConflict?.(detail)
      } else {
        errorMessage.value = detail
        notice.value = { type: 'error', message: detail }
      }
    } finally {
      isSubmitting.value = false
    }
  }

  return {
    isSubmitting,
    errorMessage,
    notice,
    resumeWorkflow,
  }
}
