import os
import time
import httpx

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CHAT_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"


def _auth_header() -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def ask_deepseek(
    query: str,
    uid: str = "",
    history: list[dict] | None = None,
    parameters: dict | None = None,
    stream: bool = False,
) -> dict:
    """调用 DeepSeek API，返回标准化响应"""
    system_prompt = "你是成电校园餐饮推荐助手，请结合用户需求、用户画像和候选信息给出清晰推荐。"
    if parameters:
        profile = parameters.get("AGENT_USER_PROFILE_SUMMARY", "")
        keywords = parameters.get("AGENT_CATEGORY_KEYWORDS", "")
        system_prompt += f"\n用户画像：{profile}\n意图关键词：{keywords}"

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": query})

    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4"),
        "messages": messages,
        "temperature": float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "1800")),
        "stream": stream,
    }

    timeout = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "25"))
    max_retries = int(os.getenv("DEEPSEEK_MAX_RETRIES", "1"))

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(CHAT_URL, headers=_auth_header(), json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                finish_reason = data.get("choices", [{}])[0].get("finish_reason", "")
                return {
                    "ok": True,
                    "answer": content,
                    "raw": data,
                    "code": 0,
                    "finish_reason": finish_reason,
                }
        except httpx.HTTPError as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_error = str(e)
            break

    return {"ok": False, "answer": "", "raw": None, "error": last_error, "code": -1}
