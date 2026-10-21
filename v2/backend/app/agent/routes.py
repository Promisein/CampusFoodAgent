import sqlite3

from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field

from app.models import RecommendationRequest
from app.agent.store import SessionError


class SessionCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    latitude:float=Field(ge=-90,le=90)
    longitude:float=Field(ge=-180,le=180)
    radius_km:float=Field(default=5,gt=0,le=50)
    max_price_level:int=Field(default=4,ge=1,le=4)
    city:str=Field(default='Tampa',min_length=1,max_length=80)
    user_id:str | None=Field(default=None,min_length=1,max_length=128,pattern=r'\S')
    top_k:int=Field(default=5,ge=1,le=5)


class TurnRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    turn_id:str=Field(min_length=1,max_length=128,pattern=r'\S')
    expected_version:int=Field(ge=0,strict=True)
    message:str=Field(min_length=1,max_length=1000,pattern=r'\S')
    use_model:bool=Field(default=False,strict=True)
    generate_answer:bool=Field(default=False,strict=True)


def register_agent_routes(app,repository,service):
    def safe(fn):
        try:return fn()
        except SessionError as error:raise HTTPException(error.status,detail=error.reason) from None
        except (OSError,sqlite3.Error):raise HTTPException(503,detail='agent_store_unavailable_or_busy') from None

    @app.post('/api/v2/agent/sessions',status_code=201)
    def create_session(payload:SessionCreate):
        return safe(lambda:repository().create(payload.model_dump()))

    @app.get('/api/v2/agent/sessions/{session_id}')
    def session(session_id:str):return safe(lambda:repository().get(session_id))

    @app.post('/api/v2/agent/sessions/{session_id}/turns')
    def turn(session_id:str,payload:TurnRequest):
        data=payload.model_dump()
        return safe(lambda:repository().turn(session_id,data,lambda state:service().execute(session_id,data,state)))
