"""Local-only credentials. Public status never includes credential material."""
import math
import os
import re
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_ENV=Path(__file__).resolve().parents[2]/'.env'


@dataclass(frozen=True)
class RagSettings:
    api_key: str=field(default='',repr=False)
    model: str='deepseek-flash'
    base_url: str='https://api.deepseek.com'
    enabled: bool=True
    timeout_seconds: float=12
    max_tokens: int=1800
    max_context_chars: int=24000
    max_restaurants: int=5

    def __post_init__(self):
        url=urlparse(self.base_url)
        if url.scheme!='https' or url.hostname!='api.deepseek.com' or url.username or url.password or url.port or url.query or url.fragment or url.path.rstrip('/') not in ('','/v1'):
            raise ValueError('Invalid DEEPSEEK_BASE_URL; use official HTTPS endpoint')
        if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,80}',self.model):raise ValueError('Invalid DEEPSEEK_MODEL')
        if not math.isfinite(self.timeout_seconds) or not 1<=self.timeout_seconds<=60:raise ValueError('Invalid RAG_TIMEOUT_SECONDS')
        if not 128<=self.max_tokens<=8192:raise ValueError('Invalid RAG_MAX_TOKENS')
        if not 4000<=self.max_context_chars<=40000:raise ValueError('Invalid RAG_MAX_CONTEXT_CHARS')
        if not 1<=self.max_restaurants<=10:raise ValueError('Invalid RAG_MAX_RESTAURANTS')
        if any(c in self.api_key for c in '\r\n'):raise ValueError('Invalid credential format')

    def public_status(self):
        return {'version':'rag_v1','enabled':self.enabled,'configured':bool(self.api_key),
                'model':self.model,'mode':'deepseek_structured_plan_with_verified_rendering',
                'live_probe':'not_performed_by_status','credential_location':'v2/backend/.env'}


def load_settings(path=DEFAULT_ENV,*,environ=None):
    env=os.environ if environ is None else environ
    local={}
    path=Path(path)
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if '=' not in line:raise ValueError('Invalid local environment file syntax')
            key,value=line.split('=',1);key=key.strip();value=value.strip()
            if key in local:raise ValueError('Duplicate local environment setting')
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            local[key]=value
    def get(key,default):return env[key] if key in env else local.get(key,default)
    raw_enabled=get('RAG_ENABLED','true').lower()
    if raw_enabled not in ('true','false','1','0'):raise ValueError('Invalid RAG_ENABLED')
    try:
        timeout=float(get('RAG_TIMEOUT_SECONDS','12'));tokens=int(get('RAG_MAX_TOKENS','1800'))
        context=int(get('RAG_MAX_CONTEXT_CHARS','24000'));count=int(get('RAG_MAX_RESTAURANTS','5'))
    except (ValueError,TypeError):raise ValueError('Invalid numeric RAG configuration') from None
    return RagSettings(api_key=get('DEEPSEEK_API_KEY','').strip(),model=get('DEEPSEEK_MODEL','deepseek-flash').strip(),
        base_url=get('DEEPSEEK_BASE_URL','https://api.deepseek.com').rstrip('/'),enabled=raw_enabled in ('true','1'),
        timeout_seconds=timeout,max_tokens=tokens,max_context_chars=context,max_restaurants=count)
