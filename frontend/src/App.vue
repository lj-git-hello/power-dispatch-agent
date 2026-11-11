<script setup lang="ts">
/**
 * App —— 装配层（零业务词汇）。
 *
 * 底座不 import 任何业务模块：
 * - 业务表单由 PluginRegistry.getActive()?.formComponent 动态渲染；
 * - 端点由后端 manifest 校准（后端为唯一真相源），启动时按插件名匹配。
 */
import { computed, onMounted, ref } from 'vue'

import { fetchPluginManifest } from './core/api/plugin'
import { PluginRegistry } from './core/plugins/registry'
import WorkbenchLayout from './core/views/WorkbenchLayout.vue'
import type { ApplyResult } from './core/workbench/useWorkbenchStore'

// 工作台布局实例
const layoutRef = ref<InstanceType<typeof WorkbenchLayout> | null>(null)

/** 生效插件（main.ts 在挂载前已完成注册） */
const plugin = computed(() => PluginRegistry.getActive())

/** 非阻断提示：插件名不匹配 / 版本偏斜 / 清单同步失败 */
const notice = ref<string | null>(null)

function handleSubmitted(result: ApplyResult) {
  layoutRef.value?.handleApplied(result)
}

onMounted(async () => {
  try {
    const manifest = await fetchPluginManifest()

    // 插件名不一致 → 前端未注册该业务，明确提示，不静默失败
    if (!PluginRegistry.setActive(manifest.name)) {
      notice.value = `后端生效插件「${manifest.name}」在前端未注册，请检查前后端插件版本是否一致。`
      return
    }

    // 版本偏斜 → 控制台告警 + 顶部非阻断提示条
    const local = PluginRegistry.get(manifest.name)
    if (local && local.version !== manifest.version) {
      console.warn(
        `[插件版本偏斜] 前端=${local.version} 后端=${manifest.version}`,
      )
      notice.value = `插件版本不一致（前端 ${local.version} / 后端 ${manifest.version}），部分功能可能异常。`
    }

    // 后端 manifest 覆盖本地端点，消除前后端路径漂移
    PluginRegistry.applyManifestEndpoints(manifest.name, manifest.endpoints)

    // 演示身份同样以后端为准（通用外壳据此渲染身份切换器）
    if (manifest.identities?.length) {
      PluginRegistry.applyManifestIdentities(manifest.name, manifest.identities)
    }
  } catch (error) {
    console.error('插件清单同步失败：', error)
    notice.value = '插件清单同步失败，当前使用本地默认端点。'
  }
})
</script>

<template>
  <div class="flex h-screen flex-col">
    <!-- 插件契约偏斜提示（非阻断） -->
    <p
      v-if="notice"
      class="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-700"
    >
      {{ notice }}
    </p>

    <div class="min-h-0 flex-1">
      <WorkbenchLayout ref="layoutRef">
        <!-- 业务表单挂到底座插槽（sessionId 由插槽作用域提供） -->
        <template #business-form="{ sessionId }">
          <component
            :is="plugin?.formComponent"
            v-if="plugin?.formComponent"
            :session-id="sessionId"
            @submitted="handleSubmitted"
          />
          <p v-else class="text-xs text-gray-400">
            当前业务插件未提供填报表单
          </p>
        </template>
      </WorkbenchLayout>
    </div>
  </div>
</template>
