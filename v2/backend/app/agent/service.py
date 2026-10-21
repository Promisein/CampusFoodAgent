"""Bounded tool graph. The planner proposes; explicit user intent authorizes."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import sqlite3
import time
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,StrictInt

from app.agent.state import Clarification,action_for_message,merge_slots,query_for_slots,resolve_reference
from app.models import RecommendationRequest,RecommendationResponse
from app.rag.generation import AnswerService,ProviderFailure
from app.rag.settings import RagSettings
from app.agent.semantic import interpret,SEMANTIC_PROMPT,explicit_resolution,policy_issues,rule_resolution_remainder
from app.agent.messages import issue_message
from app.query_intent import CATEGORIES,SOFT_TOPICS

PLAN_PROMPT=SEMANTIC_PROMPT


class ActionPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['search','explain','favorite','history','favorites','clarify']
    index:StrictInt | None=Field(default=None,ge=1,le=5)


class BudgetExceeded(ValueError):pass


class Budget:
    def __init__(self,*,seconds=10,max_steps=4,clock=time.monotonic):
        self.clock,self.deadline,self.max_steps=clock,clock()+seconds,max_steps
        self.trace=[];self.provider_calls=0

    def remaining(self):return max(0,self.deadline-self.clock())

    def call(self,name,fn,*,write=False):
        if len(self.trace)>=self.max_steps or self.remaining()<=0:raise BudgetExceeded('turn_budget_exhausted')
        started=self.clock();entry={'tool':name,'status':'running','write':write}
        self.trace.append(entry)
        try:result=fn()
        except Exception:
            entry.update(status='failed',elapsed_seconds=round(self.clock()-started,6))
            raise
        entry.update(status='completed',elapsed_seconds=round(self.clock()-started,6))
        # Cooperative deadline: CPU/database work cannot be preempted safely.
        # A completed write is never misreported as cancelled.
        if not self.remaining():entry['deadline_exceeded_after_completion']=True
        return result

    def provider_settings(self,settings,*,planner=False):
        if self.provider_calls>=1 or self.remaining()<1:raise BudgetExceeded('model_budget_exhausted')
        self.provider_calls+=1
        return replace(settings,timeout_seconds=max(1,min(6,self.remaining(),settings.timeout_seconds)),
                       max_tokens=min(1400 if planner else 1800,settings.max_tokens))


class AgentService:
    def __init__(self,*,recommend,events,reviews,settings,planner_provider,budget_factory=Budget):
        self.recommend,self.events,self.reviews=recommend,events,reviews
        self.settings,self.planner_provider,self.budget_factory=settings,planner_provider,budget_factory

    def execute(self,session_id,payload,state):
        budget=self.budget_factory()
        action=action_for_message(payload['message'])['action']
        requested_action=action
        semantic_result=None;reference_message=payload['message']
        simple_explanation=bool(re.fullmatch(r'(?:请|帮我)?(?:解释|介绍)(?:一下)?第[一二三四五\d]+(?:家|个)[。.!！]?|explain (?:the )?(?:first|second|third|fourth|fifth)(?: one)?',payload['message'].strip(),re.I))
        planner={'mode':'rules','reason':None,'provider_attempted':False,'usage':{}}
        reply={'status':'completed','action':action,'answer':None,'focused_business_id':None}
        try:
            if payload.get('use_model') and not (simple_explanation and payload.get('generate_answer')):
                try:
                    settings=self.settings()
                    if settings.enabled and settings.api_key:
                        bounded=budget.provider_settings(settings,planner=True)
                        planner['provider_attempted']=True
                        proposal,usage=budget.call('plan_action',lambda:self.planner_provider(bounded).complete(
                            {'message':payload['message'],'has_results':bool(state['last_response']),
                             'current_slots':state['slots'],'pending_request':state.get('pending_semantic'),
                             'recent_dialogue':[{**m,'text':m['text'][:1000]} for m in state['messages'][-4:]],
                             'supported_categories':list(CATEGORIES),'supported_topics':list(SOFT_TOPICS),
                             'current_restaurants':[{'index':n,'name':r['name'][:160]} for n,r in enumerate((state['last_response'] or {}).get('recommendations',[]),1)],
                             'allowed_actions':['search','explain','favorite','history','favorites','clarify']}))
                        planner['usage']=usage
                        if isinstance(proposal,dict) and any(k in proposal for k in ('changes','issues','resolved','reference_quote')):
                            candidate=interpret(proposal,state,payload['message'])
                            plan=candidate['plan']
                            if plan.action=='favorite' and action!='favorite':
                                requested_action='favorite'
                                raise Clarification('你是想收藏某家餐厅吗？请明确回复“收藏第二家”这样的指令，我不会自动执行。')
                            if plan.index is not None:
                                if plan.action not in ('explain','favorite'):raise ValueError('unexpected_reference')
                                target=resolve_reference(state,f'第{plan.index}家')
                                try:original=resolve_reference(state,payload['message'])
                                except Clarification:
                                    if plan.action=='favorite' or not plan.reference_quote or plan.reference_quote not in payload['message']:raise ValueError('reference_missing')
                                else:
                                    if original!=target:raise ValueError('reference_mismatch')
                                reference_message=f'第{plan.index}家'
                            if plan.action in ('explain','favorite','history','favorites') and plan.changes:raise ValueError('mixed_action_and_filter_update')
                            action=plan.action
                            if action=='search':requested_action='search'
                            semantic_result=candidate
                            planner.update(mode='deepseek_semantic',usage=usage)
                            planner['extracted_changes']=[c.model_dump() for c in plan.changes]
                        else:
                            plan=ActionPlan.model_validate(proposal)
                            if plan.action not in (action,'clarify'):raise ValueError('action_not_authorized')
                            if plan.index is not None:
                                if action not in ('explain','favorite'):raise ValueError('unexpected_reference')
                                if resolve_reference(state,payload['message'])!=resolve_reference(state,f'第{plan.index}家'):raise ValueError('reference_mismatch')
                            action=plan.action
                            planner.update(mode='deepseek_action',usage=usage)
                    else:planner['reason']='model_not_configured_or_disabled'
                except Clarification:raise
                except (ValueError,OSError,TypeError,KeyError,IndexError):planner['reason']='planner_failed_or_rejected'
            elif payload.get('use_model'):
                planner['reason']='model_budget_reserved_for_explanation'

            reply['action']=action
            if semantic_result and semantic_result['issues']:
                state['pending_semantic']={'slots':semantic_result['slots'],'issues':semantic_result['issues'],
                    'source_text':((state.get('pending_semantic') or {}).get('source_text','')+'\n'+payload['message'])[-4000:]}
                state['pending_clarification']=True
                raise Clarification(semantic_result['message'])
            if action=='clarify':raise Clarification('请明确搜索条件或指定当前餐厅，例如解释第二家、收藏第二家。')
            if action=='search':
                if semantic_result is None:
                    current_issues=policy_issues(payload['message'],[])
                    if current_issues:raise Clarification(issue_message(current_issues))
                if semantic_result:slots=semantic_result['slots']
                elif state.get('pending_semantic'):
                    pending=state['pending_semantic']
                    remainder=rule_resolution_remainder(payload['message'],pending['issues'])
                    slots=(merge_slots({**state,'slots':pending['slots']},remainder) if remainder else deepcopy(pending['slots']))
                    unresolved=[i for i in pending['issues'] if explicit_resolution(i['code'],payload['message'],[]) is not True]
                    if unresolved:
                        state['pending_semantic']={**pending,'slots':slots,'issues':unresolved}
                        raise Clarification(issue_message(unresolved))
                else:slots=merge_slots(state,payload['message'])
                context=state['context']
                request=RecommendationRequest(**{**context,'query':query_for_slots(slots),
                    'radius_km':slots['radius_km'],'max_price_level':slots['max_price_level'],'generate_answer':False})
                response=budget.call('search_restaurants',lambda:self.recommend(request))
                if response.engine=='query_needs_clarification':raise Clarification('条件需要澄清，请修改后重试。')
                snapshot=response.model_dump()
                # Session storage retains quotes rather than full review bodies.
                for rec in snapshot['recommendations']:
                    for evidence in rec['evidence']:evidence['text']=evidence.get('excerpt') or ''
                state.update(slots=slots,last_response=snapshot,last_request=request.model_dump(),
                             focus_business_id=None,pending_clarification=False,pending_semantic=None)
                count=len(snapshot['recommendations'])
                reply['message']=(f'找到{count}家餐厅。价格上限为等级{slots["max_price_level"]}，半径{slots["radius_km"]:g}公里。'
                                  if count else '没有符合当前条件的餐厅，请调整类别、半径或价格等级。')
                if semantic_result:
                    category_labels={'coffee':'咖啡/咖啡馆','pizza':'披萨','chinese':'中餐','japanese':'日料','sushi':'寿司',
                        'mexican':'墨西哥菜','thai':'泰餐','italian':'意大利菜','burgers':'汉堡','seafood':'海鲜',
                        'breakfast':'早餐/早午餐','vegan':'纯素','vegetarian':'素食'}
                    categories='、'.join(category_labels.get(k,k) for k in slots['include']) or '不限定菜系'
                    labels={'date':'约会','quiet':'安静','conversation':'聊天','outdoor':'户外座位','formal':'正式体面环境',
                            'hosting':'请客聚会','family':'亲子','work':'学习办公','parking':'停车','value':'性价比'}
                    preferences='、'.join(labels.get(k,k) for k in slots['topics'])
                    reply['message']='我理解为：'+categories+('；偏好'+preferences if preferences else '')+'。'+reply['message']
                    if slots['exclude']:reply['message']+='\n已排除：'+'、'.join(category_labels.get(k,k) for k in slots['exclude'])+'。'
                    if preferences:reply['message']+='\n环境与场景只作软偏好，需核对评论；我不能保证门店实际满足。'
            elif action=='explain':
                business_id=resolve_reference(state,reference_message)
                selected=next(r for r in state['last_response']['recommendations'] if r['business_id']==business_id)
                response=RecommendationResponse(version='v2',engine='agent_current_result',recommendations=[selected])
                request=RecommendationRequest(**state['last_request'])
                reviews=budget.call('retrieve_evidence',self.reviews)
                settings=RagSettings()
                if payload.get('generate_answer'):
                    try:
                        configured=self.settings()
                        if configured.api_key and configured.enabled and budget.provider_calls==0:settings=budget.provider_settings(configured)
                    except (OSError,ValueError,TypeError):pass
                answer=budget.call('explain_restaurant',lambda:AnswerService(settings).generate(request,response,reviews))
                # Reserving a call is an upper bound; context/clarification may skip it.
                if settings.api_key and not answer['provider_attempted']:budget.provider_calls-=1
                reply.update(answer=answer,focused_business_id=business_id,message=answer['text'])
                state['focus_business_id']=business_id
            elif action=='favorite':
                # Recheck raw consent even when an optional model proposed the action.
                if action_for_message(payload['message'])['action']!='favorite':raise Clarification('收藏需要明确指令。')
                business_id=resolve_reference(state,payload['message'])
                request_id=state['last_response']['metadata'].get('request_id')
                if not request_id:raise Clarification('当前曝光没有成功保存，请重新搜索后再收藏。')
                event_id='agent:'+hashlib.sha256((session_id+'\0'+payload['turn_id']).encode()).hexdigest()
                event={'event_id':event_id,'request_id':request_id,'user_id':state['context'].get('user_id'),
                       'business_id':business_id,'event_type':'favorite'}
                budget.call('save_favorite',lambda:self.events().record_event(event),write=True)
                state['focus_business_id']=business_id
                reply.update(message='已收藏指定餐厅。',focused_business_id=business_id)
            elif action in ('history','favorites'):
                user_id=state['context'].get('user_id')
                if not user_id:raise Clarification('查看跨会话历史或收藏需要在新会话中填写演示用户ID。')
                if action=='history':
                    reply['events']=budget.call('get_history',lambda:self.events().history(user_id,limit=50))
                    reply['message']=f'找到{len(reply["events"])}条本地反馈记录。'
                else:
                    favorites=budget.call('get_favorites',lambda:self.events().favorites(user_id))
                    reply['favorites']=[{'business_id':r['business_id'],'name':r['name']} for r in favorites[:50]]
                    reply['message']=f'展示{len(reply["favorites"])}家已收藏餐厅。'
        except Clarification as error:
            if requested_action=='search':
                state['pending_clarification']=True
                # A failed/unavailable semantic call must not erase a hard
                # condition merely because the next turn changes cuisine.
                if semantic_result is None:
                    current_issues=[i for i in policy_issues(payload['message'],[])
                                    if i['code'] in ('currency_budget','live_availability','dietary_guarantee','unverifiable_preference')]
                    if current_issues:
                        pending=state.get('pending_semantic') or {}
                        issues={i['code']:i for i in pending.get('issues',[])+current_issues}
                        state['pending_semantic']={'slots':pending.get('slots') or deepcopy(state['slots']),
                            'issues':list(issues.values())[:5],
                            'source_text':(pending.get('source_text','')+'\n'+payload['message'])[-4000:]}
            reply.update(status='needs_clarification',message=str(error))
            if planner['mode']=='rules' and payload.get('use_model') and planner['reason']:
                reply['message']+='\n自然语言理解暂未成功启用，本轮使用有限规则处理。'
        except BudgetExceeded:
            if requested_action=='search':state['pending_clarification']=True
            reply.update(status='limit_exceeded',message='本轮执行预算已用完，请缩短请求或稍后重试。')
        except (OSError,ValueError,TypeError,KeyError,IndexError,sqlite3.Error,HTTPException):
            if requested_action=='search':state['pending_clarification']=True
            reply.update(status='tool_unavailable',message='本地工具暂不可用，请重试；没有放宽查询条件。')
        reply['recommendations']=[] if state['pending_clarification'] else (state['last_response'] or {}).get('recommendations',[])
        reply.update(planner=planner,trace=budget.trace,budget={'provider_calls':budget.provider_calls,
            'max_provider_calls':1,'max_steps':budget.max_steps,'remaining_seconds':round(budget.remaining(),6),
            'deadline_semantics':'cooperative; completed side effects are not cancelled'})
        return reply
