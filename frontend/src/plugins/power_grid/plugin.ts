/**
 * 电力业务插件清单（前端）。
 *
 * 通用底座只认 PluginDefinition，不认任何业务细节：
 * 新增业务 = 新增 src/plugins/<biz>/plugin.ts，main.ts 与 core/ 零改动。
 * 端点路径以本地声明为默认值，启动时由后端 manifest 覆盖（后端是唯一真相源）。
 */

import type { WorkflowEndpoints } from '@/core/a2ui/types'
import type { PluginDefinition, PluginIdentity } from '@/core/plugins/registry'

import CitationsCard from './cards/CitationsCard.vue'
import PermitResultCard from './cards/PermitResultCard.vue'
import SafetyDiffCard from './cards/SafetyDiffCard.vue'
import SubstationApplyForm from './forms/SubstationApplyForm.vue'

/** 插件唯一名（须与后端 app/plugins/power_grid/plugin.py 的 name 一致） */
export const POWER_PLUGIN_NAME = 'power_grid'
/** 插件版本（须与后端 manifest 的 version 一致） */
export const POWER_PLUGIN_VERSION = '1.0.0'

/** 电力业务角色（语义由本插件解释） */
export const POWER_ROLE_APPLICANT = 'APPLICANT'
export const POWER_ROLE_DISPATCHER = 'DISPATCHER'

/**
 * 电力插件端点（相对 /api）。
 * 后端挂载前缀 /api/v1/power-dispatch → 实际请求 /api/v1/power-dispatch/*
 */
export const POWER_ENDPOINTS: WorkflowEndpoints = {
  tasks: '/v1/power-dispatch/tasks',
  messages: '/v1/power-dispatch/messages',
  resume: '/v1/power-dispatch/audit',
  apply: '/v1/power-dispatch/apply',
}

/** 演示身份（通用外壳身份切换器的数据源；后端 manifest 会覆盖） */
export const POWER_IDENTITIES: PluginIdentity[] = [
  { id: 'applicant_01', label: '张三', role: POWER_ROLE_APPLICANT },
  { id: 'dispatcher_lead', label: '王调度长', role: POWER_ROLE_DISPATCHER },
]

/** 插件清单（由 main.ts 的 import.meta.glob 自动装载） */
export const plugin: PluginDefinition = {
  name: POWER_PLUGIN_NAME,
  version: POWER_PLUGIN_VERSION,
  endpoints: POWER_ENDPOINTS,
  cards: {
    // 后端实际下发的 card_type
    dispatcher_audit: SafetyDiffCard,
    permit_result: PermitResultCard,
    power_grid_citations: CitationsCard,
    // 名称别名，兼容直接以卡片名注册的场景
    SafetyDiffCard,
    PermitResultCard,
  },
  formComponent: SubstationApplyForm,
  identities: POWER_IDENTITIES,
}

export { SubstationApplyForm }

export default plugin
