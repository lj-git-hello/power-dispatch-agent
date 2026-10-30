<template>
  <div class="permit-card" :class="isPermitted ? 'theme-permitted' : 'theme-rejected'">
    <!-- 电子票据锯齿边 -->
    <div class="ticket-top" :class="isPermitted ? 'zigzag-green' : 'zigzag-red'"></div>

    <div class="ticket-body">
      <div class="ticket-header">
        <div class="ticket-org">
          <span class="org-name">电网调度控制中心</span>
          <span class="org-sub">ELECTRIC DISPATCH CONTROL CENTER</span>
        </div>
        <div class="seal" :class="isPermitted ? 'seal-ok' : 'seal-reject'">
          <span>{{ isPermitted ? '调度许可已生效' : '申请已被调度控制中心驳回' }}</span>
        </div>
      </div>

      <div class="ticket-divider">
        <span class="divider-hole"></span>
      </div>

      <div class="ticket-rows">
        <div class="ticket-row">
          <span class="row-label">凭证编号</span>
          <span class="row-value mono">{{ cardData.permit_no ?? '未签发' }}</span>
        </div>
        <div class="ticket-row">
          <span class="row-label">关联工单</span>
          <span class="row-value mono">{{ cardData.plan_id ?? '—' }}</span>
        </div>
        <div class="ticket-row">
          <span class="row-label">流程状态</span>
          <span class="row-value" :class="isPermitted ? 'text-ok' : 'text-reject'">
            {{ cardData.status ?? '—' }}
          </span>
        </div>
      </div>

      <div class="ticket-footer">
        {{ isPermitted
          ? '现场工作负责人可据此编号办理工作票许可手续，正式开工。'
          : '本次检修申请未获核准，请依据安规意见整改后重新申报。' }}
      </div>
    </div>

    <div class="ticket-bottom" :class="isPermitted ? 'zigzag-green' : 'zigzag-red'"></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { PermitResultCardData } from '@/api/agent';

const props = defineProps<{
  cardData: PermitResultCardData;
}>();

/** 签发判定：status 为 PERMITTED 即电子凭证生效 */
const isPermitted = computed<boolean>(() => props.cardData.status === 'PERMITTED');
</script>

<style scoped>
.permit-card {
  margin-top: 12px;
  width: 100%;
  max-width: 520px;
  filter: drop-shadow(0 4px 14px rgba(15, 23, 42, 0.16));
  font-family: var(--sans, system-ui, 'Segoe UI', sans-serif);
}

.theme-permitted {
  background: #f0fdf4;
}

.theme-rejected {
  background: #fef2f2;
}

/* 票据上下锯齿边（仿电子票据撕边） */
.zigzag-green,
.zigzag-red {
  height: 8px;
  background-size: 16px 8px;
  background-repeat: repeat-x;
}

.zigzag-green {
  background-image: linear-gradient(45deg, transparent 50%, #f0fdf4 50%),
    linear-gradient(-45deg, transparent 50%, #f0fdf4 50%);
  background-position: 0 0, 8px 0;
}

.zigzag-red {
  background-image: linear-gradient(45deg, transparent 50%, #fef2f2 50%),
    linear-gradient(-45deg, transparent 50%, #fef2f2 50%);
  background-position: 0 0, 8px 0;
}

.ticket-body {
  border-top: 1px dashed #94a3b8;
  border-bottom: 1px dashed #94a3b8;
  padding: 16px 18px 12px;
}

.ticket-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.ticket-org {
  display: flex;
  flex-direction: column;
}

.org-name {
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 2px;
  color: #0f172a;
}

.org-sub {
  font-size: 9px;
  letter-spacing: 1.6px;
  color: #94a3b8;
  margin-top: 2px;
}

/* 圆形电子印章徽标 */
.seal {
  width: 86px;
  height: 86px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.4;
  padding: 10px;
  box-sizing: border-box;
  border: 3px double;
  transform: rotate(-12deg);
  flex-shrink: 0;
}

.seal span {
  display: block;
}

.seal-ok {
  color: #15803d;
  border-color: #16a34a;
  background: radial-gradient(circle, rgba(22, 163, 74, 0.08) 0%, transparent 72%);
}

.seal-reject {
  color: #b91c1c;
  border-color: #dc2626;
  background: radial-gradient(circle, rgba(220, 38, 38, 0.08) 0%, transparent 72%);
}

.ticket-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  margin: 14px -18px;
}

.ticket-divider::before,
.ticket-divider::after {
  content: '';
  flex: 1;
  border-top: 2px dashed #cbd5e1;
}

.divider-hole {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--seal-hold-color);
  margin: 0 -7px;
  box-shadow: inset 0 1px 3px rgba(15, 23, 42, 0.18);
}

.ticket-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ticket-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}

.row-label {
  font-size: 12px;
  color: #64748b;
  letter-spacing: 1px;
  flex-shrink: 0;
}

.row-value {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  text-align: right;
  word-break: break-all;
}

.row-value.mono {
  font-family: var(--mono, ui-monospace, Consolas, monospace);
  letter-spacing: 0.5px;
}

.text-ok {
  color: #15803d;
}

.text-reject {
  color: #b91c1c;
}

.ticket-footer {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed #cbd5e1;
  font-size: 11.5px;
  line-height: 1.6;
  color: #64748b;
}
</style>
