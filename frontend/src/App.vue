<template>
  <div class="dispatch-container">
    <header class="header">
      <h2>⚡ 电网检修作业调度协同中枢 (Human-in-the-Loop)</h2>
    </header>

    <main class="main-content">
      <!-- 1. 班组填报区 -->
      <section class="card form-section">
        <h3>📝 运检作业计划申报</h3>
        <div class="form-group">
          <label>作业单号 (Thread ID):</label>
          <input v-model="form.plan_id" disabled />
        </div>
        <div class="form-group">
          <label>目标变电站:</label>
          <input v-model="form.substation_name" placeholder="例如：110kV 舜耕变电站" />
        </div>
        <div class="form-group">
          <label>电压等级:</label>
          <select v-model="form.voltage_level">
            <option value="10kV">10kV (常规低压，自动流转)</option>
            <option value="110kV">110kV (高压重大检修，触发熔断)</option>
            <option value="220kV">220kV (超高压重大检修，触发熔断)</option>
          </select>
        </div>
        <div class="form-group">
          <label>检修内容:</label>
          <input v-model="form.work_content" placeholder="作业任务" />
        </div>
        <div class="form-group">
          <label>现场安措:</label>
          <input v-model="form.safety_measures" placeholder="安措方案" />
        </div>
        <button class="btn btn-primary" :disabled="loading" @click="handleApply">
          {{ loading ? '研判流转中...' : '提交申报' }}
        </button>
      </section>

      <!-- 2. AI 安规分析与状态监控区 -->
      <section class="card status-section">
        <h3>🔍 安规流式研判与控制台</h3>
        <div class="terminal">
          <p v-if="!auditReport && !loading" class="placeholder">> 等待班组提交检修计划...</p>
          <pre v-if="auditReport">{{ auditReport }}</pre>
        </div>

        <!-- 3. A2UI 动态卡片：流程挂起时呈现 -->
        <div v-if="isInterrupted" class="approval-card">
          <h4>⚠️ 调度长人工许可核签</h4>
          <p>当前作业触发高压重大检修熔断机制，流程已冻结入库，等待调度长确认开工条件：</p>
          <div class="actions">
            <button class="btn btn-success" @click="handlePermit(true)">批准并签发调度令</button>
            <button class="btn btn-danger" @click="handlePermit(false)">驳回重报</button>
          </div>
        </div>

        <!-- 4. 结案通知 -->
        <div v-if="finalPermitNo" class="success-card">
          🎉 调度令已下达！许可令编号：<strong>{{ finalPermitNo }}</strong>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import axios from 'axios';
import { fetchDispatchStream, type PlanApplyPayload } from './api/dispatch';

const form = ref<PlanApplyPayload>({
  plan_id: 'PLAN_' + Date.now(),
  substation_name: '110kV 舜耕变电站',
  voltage_level: '110kV',
  work_content: '1号主变套管消缺与绝缘油化验',
  safety_measures: '两票三制已准备，已悬挂接地线，下游科技园负荷已倒闸转供',
});

const loading = ref(false);
const auditReport = ref('');
const isInterrupted = ref(false);
const finalPermitNo = ref('');

// 提交申请，消费 SSE 流
const handleApply = async () => {
  loading.value = true;
  auditReport.value = '';
  isInterrupted.value = false;
  finalPermitNo.value = '';

  await fetchDispatchStream(form.value, (event) => {
    if (event.type === 'token') {
      // 逐字符累加进打字机
      auditReport.value += event.content || '';
    } else if (event.type === 'workflow_interrupt') {
      isInterrupted.value = true;
      loading.value = false;
    }
  });
  loading.value = false;
};

// 调度长核签唤醒
const handlePermit = async (permitted: boolean) => {
  const res = await axios.post('http://127.0.0.1:8000/api/v1/dispatch/permit', {
    plan_id: form.value.plan_id,
    permitted,
  });

  const data = res.data.data;
  auditReport.value = data.audit_report;
  isInterrupted.value = false;
  if (data.permit_no) {
    finalPermitNo.value = data.permit_no;
  }
};
</script>

<style scoped>
.dispatch-container {
  max-width: 1100px;
  margin: 30px auto;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #1e293b;
}

.header {
  border-bottom: 2px solid #e2e8f0;
  padding-bottom: 15px;
  margin-bottom: 25px;
}

.main-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.card {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-weight: 600;
  margin-bottom: 4px;
  font-size: 14px;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #94a3b8;
  border-radius: 4px;
  font-size: 14px;
  box-sizing: border-box;
}

.btn {
  padding: 10px 16px;
  border: none;
  border-radius: 4px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary {
  background: #0284c7;
  color: white;
  width: 100%;
}

.btn-primary:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.btn-success {
  background: #16a34a;
  color: white;
  margin-right: 10px;
}

.btn-danger {
  background: #dc2626;
  color: white;
}

.terminal {
  background: #0f172a;
  color: #38bdf8;
  padding: 15px;
  border-radius: 6px;
  min-height: 180px;
  font-family: monospace;
  font-size: 13px;
  overflow-x: auto;
}

.terminal pre {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.6;
}

.placeholder {
  color: #64748b;
  margin: 0;
}

.approval-card {
  margin-top: 15px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  padding: 15px;
  border-radius: 6px;
}

.approval-card h4 {
  margin: 0 0 8px 0;
  color: #b45309;
}

.actions {
  margin-top: 12px;
}

.success-card {
  margin-top: 15px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #15803d;
  padding: 12px;
  border-radius: 6px;
}
</style>