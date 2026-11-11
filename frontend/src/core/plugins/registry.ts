/**
 * PluginRegistry —— 前端业务插件注册中枢（单例，零业务词汇）。
 *
 * 各业务插件在 src/plugins/<biz>/plugin.ts 中声明自身清单，
 * 由 main.ts 通过 import.meta.glob 自动装载并注册；通用层据此解析
 * 端点、卡片与表单组件，实现"新增业务 = 新增一个插件目录"，底座零改动。
 *
 * 端点以**后端 manifest 为唯一真相源**：启动时拉取 /api/v1/plugin/manifest，
 * 按插件名匹配后覆盖本地默认值（applyManifestEndpoints）。
 */

import { computed, ref } from 'vue'
import type { Component } from 'vue'

import { CardRegistry } from '../a2ui/CardRegistry'
import type { WorkflowEndpoints } from '../a2ui/types'

/** 插件声明的演示身份（通用外壳身份切换器的数据源） */
export interface PluginIdentity {
  /** 登录账号 ID */
  id: string
  /** 展示名 */
  label: string
  /** 角色标识（语义由插件解释） */
  role: string
}

/** 插件清单（业务插件自描述） */
export interface PluginDefinition {
  /** 插件唯一名（须与后端 manifest 的 name 一致） */
  name: string
  /** 插件语义化版本（与后端 manifest 比对，检测版本偏斜） */
  version: string
  /** 工作流端点（相对 /api） */
  endpoints: WorkflowEndpoints
  /** 业务卡片：card_type → 组件（注册进通用卡片中枢） */
  cards?: Record<string, Component>
  /** 业务表单组件（宿主经动态组件渲染） */
  formComponent?: Component
  /** 演示身份（可缺省：生产环境接入企业 IAM 时无需） */
  identities?: PluginIdentity[]
}

class PluginRegistryClass {
  private readonly plugins = new Map<string, PluginDefinition>()
  /** 生效插件名（响应式：setActive 后视图自动刷新） */
  private readonly activeName = ref('')
  /** 后端 manifest 下发的端点覆盖（响应式，覆盖后视图自动刷新） */
  private readonly endpointOverrides = ref<
    Record<string, Partial<WorkflowEndpoints>>
  >({})
  /** 后端 manifest 下发的演示身份覆盖（响应式） */
  private readonly identityOverrides = ref<
    Record<string, PluginIdentity[]>
  >({})

  /** 注册插件清单；其卡片同步注册进通用卡片中枢。 */
  register(plugin: PluginDefinition): void {
    this.plugins.set(plugin.name, plugin)
    for (const [cardType, component] of Object.entries(plugin.cards ?? {})) {
      CardRegistry.register(cardType, component)
    }
    if (!this.activeName.value) {
      this.activeName.value = plugin.name
    }
  }

  /** 按名取插件清单。 */
  get(name: string): PluginDefinition | undefined {
    return this.plugins.get(name)
  }

  /** 取生效插件：显式指定优先，否则取首个已注册插件。 */
  getActive(): PluginDefinition | undefined {
    if (this.activeName.value) {
      const named = this.plugins.get(this.activeName.value)
      if (named) return named
    }
    const first = this.plugins.values().next()
    return first.done ? undefined : first.value
  }

  /** 指定生效插件；未注册返回 false（调用方应给出明确提示，不静默失败）。 */
  setActive(name: string): boolean {
    if (!this.plugins.has(name)) {
      return false
    }
    this.activeName.value = name
    return true
  }

  /** 列出全部已注册插件。 */
  list(): PluginDefinition[] {
    return [...this.plugins.values()]
  }

  /** 清空注册表（主要用于测试隔离）。 */
  clear(): void {
    this.plugins.clear()
    this.activeName.value = ''
    this.endpointOverrides.value = {}
    this.identityOverrides.value = {}
  }

  /**
   * 生效插件的端点（响应式）。
   * 本地默认值叠加后端 manifest 覆盖值；插件未注册时为 undefined。
   */
  readonly activeEndpoints = computed<WorkflowEndpoints | undefined>(() => {
    const plugin = this.getActive()
    if (!plugin) return undefined
    const override = this.endpointOverrides.value[plugin.name]
    return override ? { ...plugin.endpoints, ...override } : plugin.endpoints
  })

  /** 用后端 manifest 下发的端点覆盖本地默认值；插件未注册返回 false。 */
  applyManifestEndpoints(
    name: string,
    endpoints: Partial<WorkflowEndpoints>,
  ): boolean {
    if (!this.plugins.has(name)) {
      return false
    }
    this.endpointOverrides.value = {
      ...this.endpointOverrides.value,
      [name]: { ...(this.endpointOverrides.value[name] ?? {}), ...endpoints },
    }
    return true
  }

  /**
   * 生效插件的演示身份（响应式）。
   * 本地默认值叠加后端 manifest 覆盖值；插件未声明身份时为空数组。
   */
  readonly activeIdentities = computed<PluginIdentity[]>(() => {
    const plugin = this.getActive()
    if (!plugin) return []
    const override = this.identityOverrides.value[plugin.name]
    return override ?? plugin.identities ?? []
  })

  /** 用后端 manifest 下发的演示身份覆盖本地默认值；插件未注册返回 false。 */
  applyManifestIdentities(
    name: string,
    identities: PluginIdentity[],
  ): boolean {
    if (!this.plugins.has(name)) {
      return false
    }
    this.identityOverrides.value = {
      ...this.identityOverrides.value,
      [name]: identities,
    }
    return true
  }
}

export const PluginRegistry = new PluginRegistryClass()
