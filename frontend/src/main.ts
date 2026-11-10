import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { installPowerGridPlugin } from './plugins/power_grid'

// 装配业务插件：注册 A2UI 卡片（须在挂载前执行）
installPowerGridPlugin()

createApp(App).mount('#app')
