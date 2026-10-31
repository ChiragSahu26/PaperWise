import asyncio, json
import httpx
import config
from app.errors import PaperWiseError

class OllamaProvider:
    async def list_models(self):
        for attempt in range(config.API_RETRIES+1):
            try:
                async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
                    response=await client.get(config.OLLAMA_URL+'/api/tags')
                    if 400 <= response.status_code < 500:
                        raise PaperWiseError('INTERNAL','Ollama rejected the model-list request.',502)
                    response.raise_for_status()
                    return response.json().get('models',[])
            except (httpx.HTTPError,ValueError) as exc:
                if attempt>=config.API_RETRIES:
                    raise PaperWiseError('OLLAMA_UNAVAILABLE','Ollama is not running.',503,True,'Start Ollama and retry.') from exc
                await asyncio.sleep(config.API_BACKOFF_BASE_S*(2**attempt))

    async def health(self):
        try: return {'up':True,'models':await self.list_models()}
        except PaperWiseError: return {'up':False,'models':[]}

    async def stream(self,messages,*,model,temperature,num_ctx,max_tokens,json_schema=None):
        models=await self.list_models()
        names={m.get('name','') for m in models}
        if model not in names and (model+':latest') not in names:
            raise PaperWiseError('MODEL_NOT_INSTALLED',f'Model {model} is not installed.',400,False,f'ollama pull {model}')
        body={'model':model,'messages':messages,'stream':True,'keep_alive':config.LLM_KEEP_ALIVE,
              'options':{'num_ctx':num_ctx,'temperature':temperature,'num_predict':max_tokens}}
        if json_schema is not None: body['format']=json_schema
        sent=False
        for attempt in range(config.API_RETRIES+1):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(90,connect=5),trust_env=False) as client:
                    async with client.stream('POST',config.OLLAMA_URL+'/api/chat',json=body) as response:
                        if response.status_code>=500: response.raise_for_status()
                        if response.status_code>=400:
                            raise PaperWiseError('INTERNAL','Ollama rejected the request.',502)
                        async for line in response.aiter_lines():
                            if not line.strip(): continue
                            data=json.loads(line)
                            if data.get('error'): raise PaperWiseError('INTERNAL','Ollama reported a generation error.',502)
                            text=data.get('message',{}).get('content','')
                            if text:
                                sent=True;yield text
                            if data.get('done'): return
                        return
            except (httpx.HTTPError,json.JSONDecodeError) as exc:
                if sent or attempt>=config.API_RETRIES:
                    raise PaperWiseError('OLLAMA_UNAVAILABLE','Ollama is not running or stopped responding.',503,True,'Start Ollama and retry.') from exc
                await asyncio.sleep(config.API_BACKOFF_BASE_S*(2**attempt))

    async def complete(self,messages,**opts):
        return ''.join([part async for part in self.stream(messages,**opts)])
