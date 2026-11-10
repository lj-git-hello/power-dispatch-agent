/**
 * CardRegistry —— A2UI 卡片注册中枢（单例）。
 *
 * 各业务插件在装配时将 cardType 映射到具体卡片组件，
 * 宿主据此动态解析，实现“新增卡片类型无需改动宿主”。
 */

import type { Component } from 'vue'

class CardRegistryClass {
  private readonly components = new Map<string, Component>()

  /** 注册卡片类型对应组件。 */
  register(cardType: string, component: Component): void {
    this.components.set(cardType, component)
  }

  /** 取卡片组件；未注册返回 undefined。 */
  get(cardType: string): Component | undefined {
    return this.components.get(cardType)
  }

  /** 是否已注册某卡片类型。 */
  has(cardType: string): boolean {
    return this.components.has(cardType)
  }
}

export const CardRegistry = new CardRegistryClass()
