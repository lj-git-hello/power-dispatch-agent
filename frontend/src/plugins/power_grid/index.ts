/**
 * 电力业务插件入口。
 *
 * installPowerGridPlugin：向通用 CardRegistry 注册业务卡片，
 * 并提供端点配置与表单组件，供宿主装配。
 */

import type { WorkflowEndpoints } from '@/core/a2ui/types'
import { CardRegistry } from '@/core/a2ui/CardRegistry'

import PermitResultCard from './cards/PermitResultCard.vue'
import SafetyDiffCard from './cards/SafetyDiffCard.vue'
import SubstationApplyForm from './forms/SubstationApplyForm.vue'

/**
 * 后端电力插件端点（main 挂载前缀 /api/v1/power-dispatch；http baseURL=/api）。
 */
export const POWER_ENDPOINTS: WorkflowEndpoints = {
  tasks: '/v1/power-dispatch/tasks',
  messages: '/v1/power-dispatch/messages',
  resume: '/v1/power-dispatch/audit',
}

let installed = false

/** 注册电力业务卡片到通用卡片中枢（幂等，可重复调用）。 */
export function installPowerGridPlugin(): void {
  if (installed) return

  // 后端实际下发的 card_type 枚举
  CardRegistry.register('dispatcher_audit', SafetyDiffCard)
  CardRegistry.register('permit_result', PermitResultCard)

  // 名称别名，兼容直接以卡片名注册的场景
  CardRegistry.register('SafetyDiffCard', SafetyDiffCard)
  CardRegistry.register('PermitResultCard', PermitResultCard)

  installed = true
}

export { SubstationApplyForm, POWER_ENDPOINTS as endpoints }
