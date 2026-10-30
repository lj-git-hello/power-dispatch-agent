<template>
  <div class="approval-card" :class="{ 'is-high-risk': isHighRisk }">
    <div class="card-header">
      <span class="card-title">调度长人工核签</span>
      <span v-if="isHighRisk" class="badge badge-danger">高压警示</span>
      <span class="badge badge-warning">{{ riskLabel }}</span>
    </div>

    <div class="card-body">
      <div class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">工单编号</span>
          <span class="meta-value">{{ cardData.plan_id ?? '—' }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">电压等级</span>
          <span class="meta-value">{{ cardData.voltage_level ?? '—' }}</span>
        </div>
      </div>

      <div class="audit-report">
        <span class="meta-label">安规初审意见</span>
        <div class="report-text">{{ cardData.audit_report ?? '暂无初审意见' }}</div>
      </div>

      <div v-if="currentRole === 'DISPATCHER'" class="reason-input">
        <label for="approval-reason">审批意见（选填）</label>
        <input
          id="approval-reason"
          v-model="reason"
          type="text"
          maxlength="120"
          placeholder="如：潮流校核通过，安措完备"
        />
      </div>

      <div v-if="currentRole === 'APPLICANT'" class="locked-banner">
        【等待调度长核签中... 当前角色无操作权限】
      </div>

      <div class="card-actions">
        <button
          type="button"
          class="btn btn-approve"
          :disabled="!canOperate"
          @click="handleAction(true)"
        >
          {{ submitting && lastAction === 'approve' ? '核准流转中...' : '批准下达' }}
        </button>
        <button
          type="button"
          class="btn btn-reject"
          :disabled="!canOperate"
          @click="handleAction(false)"
        >
          {{ submitting && lastAction === 'reject' ? '驳回流转中...' : '驳回申请' }}
        </button>
      </div>

      <div v-if="resolved" class="resolved-banner">本卡已办结，审批结论已归档。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import type { ApprovalCardData, RoleType } from '@/api/agent';

/** 高压警示判定的电压等级关键字 */
const HIGH_VOLTAGE_KEYWORDS = ['110kV', '220kV', '500kV'] as const;

const props = defineProps<{
  cardData: ApprovalCardData;
  currentRole: RoleType;
  /** 父级派发的锁定态：会话已办结或全局流式执行中 */
  locked?: boolean;
}>();

const emit = defineEmits<{
  /** 调度长核签动作回传：唤醒状态机断点恢复 */
  (e: 'action', payload: { is_permitted: boolean; reason: string }): void;
}>();

const reason = ref('');
const submitting = ref(false);
const lastAction = ref<'approve' | 'reject' | ''>('');

/** 高压警示：HIGH 风险 或 电压等级命中 110kV/220kV/500kV */
const isHighRisk = computed<boolean>(() => {
  if (props.cardData.risk_level === 'HIGH') return true;
  const voltage = props.cardData.voltage_level ?? '';
  return HIGH_VOLTAGE_KEYWORDS.some((kw) => voltage.includes(kw));
});

const riskLabel = computed<string>(() =>
  props.cardData.risk_level === 'HIGH' ? '风险 HIGH' : '风险 LOW'
);

/** 已办结态：由父级依据会话终态下发 */
const resolved = computed<boolean>(() => props.locked === true && submitting.value);

/** 按钮可操作条件：调度长角色 且 未锁定 */
const canOperate = computed<boolean>(
  () => props.currentRole === 'DISPATCHER' && !props.locked && !submitting.value
);

/** 触发核签：进入 loading 锁定并上抛动作载荷 */
function handleAction(isPermitted: boolean): void {
  if (!canOperate.value) return;
  submitting.value = true;
  lastAction.value = isPermitted ? 'approve' : 'reject';
  emit('action', {
    is_permitted: isPermitted,
    reason: reason.value.trim(),
  });
}
</script>

<style scoped>
.approval-card {
  border: 1px solid #f59e0b66;
  border-left: 4px solid #f59e0b;
  border-radius: 10px;
  background: linear-gradient(160deg, #fffbeb 0%, #ffffff 65%);
  margin-top: 12px;
  overflow: hidden;
  box-shadow: 0 2px 10px rgba(245, 158, 11, 0.08);
}

.approval-card.is-high-risk {
  border: 1px solid #ef444488;
  border-left: 4px solid #ef4444;
  background: linear-gradient(160deg, #fef2f2 0%, #ffffff 65%);
  box-shadow: 0 2px 14px rgba(239, 68, 68, 0.12);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px dashed #e2e8f0;
}

.card-title {
  font-weight: 700;
  font-size: 14px;
  color: #92400e;
}

.is-high-risk .card-title {
  color: #991b1b;
}

.badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 999px;
  letter-spacing: 0.5px;
}

.badge-danger {
  background: #ef4444;
  color: #fff;
}

.badge-warning {
  background: #fef3c7;
  color: #b45309;
}

.card-body {
  padding: 14px 16px 16px;
}

.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 12px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
}

.meta-label {
  font-size: 11px;
  color: #64748b;
  letter-spacing: 0.5px;
}

.meta-value {
  font-family: var(--mono, monospace);
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.audit-report {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 12px;
}

.report-text {
  max-height: 180px;
  overflow-y: auto;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 12px;
  white-space: pre-wrap;
}

.reason-input {
  margin-bottom: 12px;
}

.reason-input label {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin-bottom: 5px;
}

.reason-input input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  background: #fff;
}

.reason-input input:focus {
  outline: none;
  border-color: #0284c7;
}

.locked-banner {
  background: #f1f5f9;
  border: 1px dashed #94a3b8;
  color: #475569;
  font-size: 12.5px;
  font-weight: 600;
  border-radius: 6px;
  padding: 9px 12px;
  text-align: center;
  margin-bottom: 12px;
}

.card-actions {
  display: flex;
  gap: 10px;
}

.btn {
  flex: 1;
  padding: 10px 0;
  border: none;
  border-radius: 6px;
  font-weight: 700;
  font-size: 13.5px;
  cursor: pointer;
  transition: opacity 0.15s ease, transform 0.1s ease;
}

.btn:not(:disabled):active {
  transform: scale(0.98);
}

.btn-approve {
  background: #16a34a;
  color: #fff;
}

.btn-reject {
  background: #dc2626;
  color: #fff;
}

.btn:disabled {
  background: #cbd5e1;
  color: #64748b;
  cursor: not-allowed;
}

.resolved-banner {
  margin-top: 10px;
  font-size: 12px;
  color: #64748b;
  text-align: center;
}
</style>
