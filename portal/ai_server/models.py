from pydantic import BaseModel,ConfigDict,Field


class AgentProfile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    assistant_name: str=Field(default='Win',min_length=1,max_length=80)
    robot_name: str=Field(default='WeWIN staging',min_length=1,max_length=120)
    system_prompt: str=Field(default='',max_length=12000)
    persona: str=Field(default='Bạn là Win, trợ lý AI giáo dục WeWIN.',max_length=6000)
    greeting: str=Field(default='Win nghe đây ạ!',max_length=300)
    language: str=Field(default='vi-VN',pattern='^(vi-VN|en-US|en)$')
    voice: str=Field(default='F1',pattern='^[FM][1-5]$')
    ai_model: str=Field(min_length=1,max_length=120)
    speech_rate: float=Field(default=1,ge=.7,le=2)
    ai_role: str=Field(default='',max_length=120)
    role_version: int=Field(default=0,ge=0)


class ApplyRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision: int=Field(ge=0)
    operation_id: str=Field(min_length=16,max_length=100,pattern='^[a-zA-Z0-9_-]+$')
    config: AgentProfile


class DeviceRegistration(BaseModel):
    model_config=ConfigDict(extra='forbid')
    device_id: str=Field(min_length=6,max_length=100,pattern='^[a-zA-Z0-9_:-]+$')
    client_id: str=Field(min_length=6,max_length=100,pattern='^[a-zA-Z0-9_-]+$')
    agent_id: str=Field(min_length=1,max_length=120,pattern='^[a-zA-Z0-9_-]+$')
    kind: str=Field(default='simulator',pattern='^(simulator|physical)$')


class Confirmation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmed: bool=False
