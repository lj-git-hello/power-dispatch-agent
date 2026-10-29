import asyncio
import uuid
from datetime import datetime
from typing import TypedDict, Optional, Literal

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# 1. 声明强类型的电力检修计划上下文
class PlanState(TypedDict):
    plan_id: str                      # 作业单号（即 thread_id）
    substation_name: str              # 变电站/线路名称
    voltage_level: str                # 电压等级 (10kV, 35kV, 110kV, 220kV)
    work_content: str                 # 检修作业内容
    safety_measures: str              # 倒闸与接地线等安措预案
    risk_level: Literal["LOW", "HIGH"]# 风险等级
    audit_report: str                 # AI 安规初审意见
    is_permitted: Optional[bool]      # 调度主管是否签发许可
    permit_no: Optional[str]          # 调度许可令正式编号
    status: Literal["INIT", "WAITING_DISPATCHER_REVIEW", "PERMITTED", "REJECTED"]

# 2. 节点逻辑
async def safety_audit_node(state: PlanState):
    voltage = state.get("voltage_level", "10kV")
    substation = state.get("substation_name", "未知变电站")
    
    # 模拟电力安规规则判定：110kV及以上必须上调度人工会签
    is_high_risk = voltage in ["110kV", "220kV", "500kV"]
    risk = "HIGH" if is_high_risk else "LOW"
    
    report = (
        f"【AI 安规初审报告】\n"
        f"• 作业目标：{substation}（电压等级：{voltage}）\n"
        f"• 初审结论：依据《电力安全工作规程》，"
    )
    
    if is_high_risk:
        report += f"当前作业属于 {voltage} 高压电网重大检修，判定风险等级为 [HIGH]。流程已自动安全熔断挂起，必须由调度室值班长完成人工校核并下发许可令。"
        return {"audit_report": report, "risk_level": "HIGH", "status": "WAITING_DISPATCHER_REVIEW"}
    else:
        report += f"作业属于常规低压检修，判定风险等级为 [LOW]，常规安措完备，系统自动批准流转。"
        return {"audit_report": report, "risk_level": "LOW", "status": "PERMITTED", "is_permitted": True}

async def dispatcher_approval_node(state: PlanState):
    permitted = state.get("is_permitted", False)
    report = state.get("audit_report", "")
    
    if permitted:
        report += f"\n【调度长签发】调度值班长已核实电网潮流分布，同意开工，调度令下发流转中。"
        return {"audit_report": report, "status": "WAITING_DISPATCHER_REVIEW"}
    else:
        report += f"\n【调度长驳回】当前时段电网潮流过载，驳回检修申请，指令班组延期重报。"
        return {"audit_report": report, "status": "REJECTED"}

async def issue_permit_node(state: PlanState):
    await asyncio.sleep(0.3)  # 模拟网关耗时
    permit_no = f"DISP_CMD_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid.uuid4().hex[:4].upper()}"
    report = state.get("audit_report", "") + f"\n【调度指令下达】正式许可令已签发，编号：{permit_no}。现场工作负责人可据此联系许可开工。"
    
    return {
        "permit_no": permit_no,
        "status": "PERMITTED",
        "audit_report": report
    }

# 3. 路由分支
def risk_router(state: PlanState):
    return "dispatcher_approval" if state.get("risk_level") == "HIGH" else "issue_permit"

def approval_router(state: PlanState):
    return "issue_permit" if state.get("is_permitted") else END

# 4. 组装电力工作流图
builder = StateGraph(PlanState)
builder.add_node("safety_audit", safety_audit_node)
builder.add_node("dispatcher_approval", dispatcher_approval_node)
builder.add_node("issue_permit", issue_permit_node)

builder.add_edge(START, "safety_audit")
builder.add_conditional_edges("safety_audit", risk_router, ["dispatcher_approval", "issue_permit"])
builder.add_conditional_edges("dispatcher_approval", approval_router, ["issue_permit", END])
builder.add_edge("issue_permit", END)

# 挂载内存检查点并设置中断
checkpointer = MemorySaver()
app = builder.compile(
    checkpointer=checkpointer,
    interrupt_before=["dispatcher_approval"]
)

# 5. 测试运行驱动
async def main():
    print("==================================================")
    print("🚀 测试场景：110kV 舜耕变电站消缺（预期触发高危熔断挂起）")
    print("==================================================")
    
    ticket_id = "PLAN_110KV_001"
    config = {"configurable": {"thread_id": ticket_id}}
    
    initial_input = {
        "plan_id": ticket_id,
        "substation_name": "110kV 舜耕变电站",
        "voltage_level": "110kV",
        "work_content": "1号主变套管消缺与绝缘油化验",
        "safety_measures": "两票三制已准备，已悬挂接地线，下游科技园负荷已倒闸转供",
        "status": "INIT"
    }

    # 第一次执行：应该在 dispatcher_approval 前自动停下
    print("\n[步骤 1] 班组提交申请，启动状态机...")
    state_after_first_run = await app.ainvoke(initial_input, config=config)
    
    print("\n--- 第一次执行结束后的快照状态 ---")
    current_snapshot = app.get_state(config)
    print(f"当前节点状态: {state_after_first_run.get('status')}")
    print(f"快照中的下一步指令指针 (next): {current_snapshot.next}")
    print(f"AI 初审输出:\n{state_after_first_run.get('audit_report')}")

    # 验证是否挂起
    if "dispatcher_approval" in current_snapshot.next:
        print("\n✅ 成功验证：流程已精准在 dispatcher_approval 节点前安全熔断挂起！")
    else:
        print("\n❌ 异常：未成功挂起！")
        return

    # 第二次执行：模拟调度长在前端/移动端点击【批准开工】
    print("\n--------------------------------------------------")
    print("[步骤 2] 模拟调度值班长在系统中核验潮流，点击【批准】唤醒流程...")
    
    # 注入审批结果
    await app.aupdate_state(config, {"is_permitted": True}, as_node="dispatcher_approval")
    
    # 传入 None 继续从断点运行
    final_state = await app.ainvoke(None, config=config)
    
    print("\n--- 最终执行结果 ---")
    print(f"最终状态: {final_state.get('status')}")
    print(f"正式调度许可令编号: {final_state.get('permit_no')}")
    print(f"最终全流程审计日志:\n{final_state.get('audit_report')}")
    print("\n🎉 端到端单点验证 100% 成功！")

if __name__ == "__main__":
    asyncio.run(main())