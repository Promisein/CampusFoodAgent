import os

from fastapi import APIRouter

from app.models.schemas import (
    DeepSeekRecommendRequest,
    DeepSeekRecommendResponse,
)
from app.services.parser import parse_query
from app.services.recommender import recommend as rule_recommend
from app.services.query_intent_service import build_query_with_intent_hint, extract_query_intents
from app.services.user_profile import build_iterative_profile
from app.services.deepseek_service import ask_deepseek
from app.services.deepseek_rerank_service import ask_deepseek_rerank

proxy_router = APIRouter()


@proxy_router.post("/recommend", response_model=DeepSeekRecommendResponse)
def post_recommend(req: DeepSeekRecommendRequest):
    provider = os.getenv("RECOMMEND_PROVIDER", "deepseek_api").strip().lower()

    # 构建用户画像（两种 AI 模式共用）
    profile = build_iterative_profile(uid=req.uid, user_id=req.userId)

    if provider == "deepseek_api":
        # ===== DeepSeek API 模式 =====
        enhanced_query = build_query_with_intent_hint(req.query)

        # 注入 AGENT_* 参数，保持后续 Prompt 与 Agent 编排扩展的一致性
        params = {
            "AGENT_USER_PROFILE_SUMMARY": profile.get("summary", ""),
            "AGENT_CATEGORY_KEYWORDS": ",".join(extract_query_intents(req.query)),
        }
        # 合并前端传来的参数
        if req.parameters:
            params.update(req.parameters)

        result = ask_deepseek(
            query=enhanced_query,
            uid=req.uid or req.anonymousId or "",
            history=req.history,
            parameters=params,
            stream=req.stream,
        )
        return DeepSeekRecommendResponse(
            ok=result["ok"],
            answer=result.get("answer", ""),
            finishReason=result.get("finish_reason", ""),
            error=result.get("error"),
            code=result.get("code", 0),
        )

    elif provider in ("deepseek_rerank", "rerank"):
        # ===== DeepSeek Rerank 模式 =====
        result = ask_deepseek_rerank(
            query=req.query,
            uid=req.uid or req.anonymousId or "",
            profile=profile,
            user_id=req.userId,
        )
        return DeepSeekRecommendResponse(
            ok=result["ok"],
            answer=result.get("answer", ""),
            recommendations=result.get("recommendations", []),
        )

    else:
        # ===== 规则引擎兜底 =====
        slots = parse_query(req.query)
        results = rule_recommend(slots, top_k=req.top_k or 3)
        return DeepSeekRecommendResponse(
            ok=True,
            answer="",
            recommendations=[
                {
                    "name": r["name"],
                    "reason": r["reason"],
                    "match_score": r["score"],
                }
                for r in results
            ],
        )
