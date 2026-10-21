"""Account-owned Web API over the existing Agent and feedback repositories."""
import hmac
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from fastapi import HTTPException,Request,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal

from app.agent.routes import SessionCreate,TurnRequest
from app.agent.store import SessionError
from app.product.accounts import AccountError,SESSION_SECONDS


COOKIE='campusfood_session'
STATIC=Path(__file__).resolve().parents[1]/'static'


class Credentials(BaseModel):
    model_config=ConfigDict(extra='forbid')
    handle:str=Field(min_length=3,max_length=32)
    password:str=Field(min_length=12,max_length=128)


class ProductSessionCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    latitude:float=Field(ge=-90,le=90)
    longitude:float=Field(ge=-180,le=180)
    radius_km:float=Field(default=5,gt=0,le=50)
    max_price_level:int=Field(default=4,ge=1,le=4)
    city:Literal['Tampa']='Tampa'
    top_k:int=Field(default=5,ge=1,le=5)


def register_product_routes(app,accounts,agents,service,events,*,secure_cookie):
    def product_scope(value):
        return {**value,'scope':'account_owned_product'}

    def safe(fn):
        try:return fn()
        except AccountError as error:raise HTTPException(error.status,error.code) from None
        except SessionError as error:raise HTTPException(error.status,error.reason) from None
        except (OSError,sqlite3.Error):raise HTTPException(503,'product_store_unavailable') from None

    def same_origin(request):
        origin=request.headers.get('origin')
        if origin and (urlsplit(origin).netloc!=request.headers.get('host') or
                       urlsplit(origin).scheme not in ('http','https')):
            raise HTTPException(403,'origin_not_allowed')

    def identity(request):
        token=request.cookies.get(COOKIE)
        account=safe(lambda:accounts().resolve_session(token))
        if not account:raise HTTPException(401,'login_required')
        return account,token

    def mutation(request):
        same_origin(request)
        account,token=identity(request)
        submitted=request.headers.get('x-csrf-token','')
        if not submitted or not hmac.compare_digest(submitted,accounts().csrf_token(token)):
            raise HTTPException(403,'csrf_token_required')
        return account,token

    def own(account,session_id):
        if not safe(lambda:accounts().owns_conversation(account['id'],session_id)):
            raise HTTPException(404,'session_not_found')

    def cookie(response,token):
        response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,
                            secure=secure_cookie(),samesite='lax',path='/')

    @app.get('/app',include_in_schema=False)
    def product_page():return FileResponse(STATIC/'product.html',media_type='text/html')

    @app.get('/app/product.css',include_in_schema=False)
    def product_styles():return FileResponse(STATIC/'product.css',media_type='text/css')

    @app.get('/app/product.js',include_in_schema=False)
    def product_script():return FileResponse(STATIC/'product.js',media_type='application/javascript')

    @app.post('/api/v2/product/register',status_code=201)
    def register(payload:Credentials,request:Request,response:Response):
        same_origin(request)
        def operation():
            account=accounts().register(payload.handle,payload.password)
            token=accounts().issue_session(account['id'])
            return account,token
        account,token=safe(operation)
        cookie(response,token)
        return {'account':account,'csrf_token':accounts().csrf_token(token)}

    @app.post('/api/v2/product/login')
    def login(payload:Credentials,request:Request,response:Response):
        same_origin(request)
        def operation():
            account=accounts().authenticate(payload.handle,payload.password)
            token=accounts().issue_session(account['id'])
            return account,token
        account,token=safe(operation)
        cookie(response,token)
        return {'account':account,'csrf_token':accounts().csrf_token(token)}

    @app.get('/api/v2/product/me')
    def me(request:Request):
        account,token=identity(request)
        return {'account':account,'csrf_token':accounts().csrf_token(token)}

    @app.post('/api/v2/product/logout')
    def logout(request:Request,response:Response):
        _,token=mutation(request)
        safe(lambda:accounts().logout(token))
        response.delete_cookie(COOKIE,path='/',samesite='lax',secure=secure_cookie())
        return {'logged_out':True}

    @app.post('/api/v2/product/sessions',status_code=201)
    def create_session(payload:ProductSessionCreate,request:Request):
        account,_=mutation(request)
        context=SessionCreate(**payload.model_dump(),user_id=account['id']).model_dump()
        def operation():
            created=agents().create(context)
            accounts().bind_conversation(account['id'],created['session_id'],'新对话')
            return created
        return product_scope(safe(operation))

    @app.get('/api/v2/product/conversations')
    def conversations(request:Request):
        account,_=identity(request)
        return {'conversations':safe(lambda:accounts().list_conversations(account['id']))}

    @app.get('/api/v2/product/sessions/{session_id}')
    def get_session(session_id:str,request:Request):
        account,_=identity(request)
        own(account,session_id)
        return product_scope(safe(lambda:agents().get(session_id)))

    @app.post('/api/v2/product/sessions/{session_id}/turns')
    def turn(session_id:str,payload:TurnRequest,request:Request):
        account,_=mutation(request)
        own(account,session_id)
        data=payload.model_dump()
        def operation():
            result=agents().turn(session_id,data,lambda state:service().execute(session_id,data,state))
            # A retry receives the cached response; touching only updates the
            # conversation list and never repeats a favorite event.
            accounts().touch_conversation(account['id'],session_id,
                payload.message if result['version']==1 else None)
            return result
        return product_scope(safe(operation))

    @app.get('/api/v2/product/favorites')
    def favorites(request:Request):
        account,_=identity(request)
        rows=safe(lambda:events().favorites(account['id']))[:50]
        return {'favorites':[{'business_id':row['business_id'],'name':row['name'],
            'city':row.get('city'),'rating':row.get('rating'),'price_level':row.get('price_level'),
            'favorited_at':row['favorited_at']} for row in rows]}

    @app.get('/api/v2/product/history')
    def history(request:Request):
        account,_=identity(request)
        return {'events':safe(lambda:events().history(account['id'],limit=50))}
