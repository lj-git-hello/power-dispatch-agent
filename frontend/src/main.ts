/**
 * 应用入口 —— 通用底座装配（不含任何业务词汇）。
 *
 * 业务插件由 Vite 的 import.meta.glob 在编译期静态展开后自动装载：
 * 新增 src/plugins/<biz>/plugin.ts 即被识别，本文件零改动。
 */
import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { PluginRegistry, type PluginDefinition } from './core/plugins/registry'

// 编译期静态展开：匹配 src/plugins/*/plugin.ts
const pluginModules = import.meta.glob('./plugins/*/plugin.ts', {
  eager: true,
}) as Record<string, { default?: PluginDefinition; plugin?: PluginDefinition }>

for (const [modulePath, module] of Object.entries(pluginModules)) {
  // 兼容 default 导出与具名 plugin 导出两种写法
  const definition = module.default ?? module.plugin
  if (!definition) {
    console.warn(`[插件装载] ${modulePath} 未导出插件清单，已跳过。`)
    continue
  }
  PluginRegistry.register(definition)
}

createApp(App).mount('#app')
