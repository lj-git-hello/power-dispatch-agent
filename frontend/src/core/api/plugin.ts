/**
 * plugin —— 插件清单契约同步（通用层）。
 *
 * 后端是端点路径的唯一真相源：前端启动时拉取活跃插件的 name / version /
 * endpoints，与本地 PluginRegistry 按 name 匹配后采用后端下发的路径，
 * 消除前后端各自硬编码路径的漂移风险。
 */

import type { WorkflowEndpoints } from '../a2ui/types'
import type { PluginIdentity } from '../plugins/registry'
import { http } from './http'

/** 后端下发的插件清单负载 */
export interface PluginManifestPayload {
  name: string
  version: string
  /** 端点路径字典（相对 /api） */
  endpoints: Partial<WorkflowEndpoints>
  /** 演示身份列表 */
  identities?: PluginIdentity[]
}

/** 拉取后端活跃插件清单。 */
export async function fetchPluginManifest(): Promise<PluginManifestPayload> {
  const { data } = await http.get<PluginManifestPayload>('/v1/plugin/manifest')
  return data
}
