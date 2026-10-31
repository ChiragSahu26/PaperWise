"""The sole internet transport for optional Paper Intelligence features."""
import asyncio, hashlib, json, time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
import httpx
import config
from app.api.settings import current_settings
from app.errors import PaperWiseError

ALLOWED={'api.semanticscholar.org','api.openalex.org','api.crossref.org','api.github.com','huggingface.co','www.googleapis.com'}
_connectivity=(0.0,False)
class OnlineNotFound(Exception):pass

def enabled():return current_settings()['online_lookups']
def ensure_enabled():
    if not enabled():raise PaperWiseError('ONLINE_FEATURE_DISABLED','Online lookups are disabled.',400)

def delay_for(value,attempt):
    if value:
        try:return max(0,float(value))
        except ValueError:
            try:return max(0,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
            except (ValueError,TypeError,OverflowError):pass
    return config.API_BACKOFF_BASE_S*(2**attempt)

async def get_json(url,*,params=None,headers=None,ttl=604800,refresh=False):
    ensure_enabled()
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in ALLOWED or parsed.username or parsed.password:
        raise ValueError('URL is not an approved online endpoint')
    params=params or {};headers=headers or {}
    # Hash credentials as part of the cache key; never write them to disk in plaintext.
    key=hashlib.sha256(json.dumps([url,params,headers],sort_keys=True).encode()).hexdigest()
    path=config.DATA_DIR/'online_cache'/f'{key}.json'
    if not refresh and path.exists() and time.time()-path.stat().st_mtime<ttl:
        try:return json.loads(path.read_text())
        except (ValueError,OSError):pass
    user_agent='PaperWise/2.0'+(f' ({config.CONTACT_EMAIL})' if config.CONTACT_EMAIL else '')
    request_headers={'User-Agent':user_agent,**headers}
    for attempt in range(config.API_RETRIES+1):
        ensure_enabled()
        try:
            async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
                response=await client.get(url,params=params,headers=request_headers)
            if response.status_code==404:raise OnlineNotFound()
            if response.status_code==429 or response.status_code>=500:
                if attempt<config.API_RETRIES:
                    await asyncio.sleep(delay_for(response.headers.get('Retry-After'),attempt));continue
                if response.status_code==429:raise PaperWiseError('RATE_LIMITED_UPSTREAM','An online provider rate-limited the request.',503,True)
                raise PaperWiseError('INTERNAL','An online provider is unavailable.',503,True)
            if response.status_code>=300:raise PaperWiseError('INTERNAL','An online provider rejected the request.',503,False)
            data=response.json()
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix('.tmp.'+str(id(asyncio.current_task())))
            temporary.write_text(json.dumps(data));temporary.replace(path)
            return data
        except (httpx.HTTPError,ValueError) as exc:
            if attempt>=config.API_RETRIES:raise PaperWiseError('INTERNAL','An online provider is unavailable.',503,True) from exc
            await asyncio.sleep(config.API_BACKOFF_BASE_S*(2**attempt))

async def connectivity():
    global _connectivity
    ensure_enabled()
    if time.monotonic()-_connectivity[0]<60:return _connectivity[1]
    try:
        await asyncio.wait_for(get_json('https://api.crossref.org/works',params={'rows':0},ttl=60),timeout=3)
        result=True
    except Exception:result=False
    _connectivity=(time.monotonic(),result)
    return result
