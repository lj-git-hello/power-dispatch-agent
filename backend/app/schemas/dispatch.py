from pydantic import BaseModel, Field

class PlanApplyRequest(BaseModel):
    plan_id: str = Field(..., description="检修计划唯一单号", example="PLAN_110KV_001")
    substation_name: str = Field(..., description="变电站名称", example="110kV 舜耕变电站")
    voltage_level: str = Field(..., description="电压等级", example="110kV")
    work_content: str = Field(..., description="检修作业内容", example="1号主变套管消缺")
    safety_measures: str = Field(..., description="安措预案", example="两票三制已准备，已悬挂接地线")

class PermitRequest(BaseModel):
    plan_id: str = Field(..., description="检修计划单号", example="PLAN_110KV_001")
    permitted: bool = Field(..., description="是否核准签发", example=True)