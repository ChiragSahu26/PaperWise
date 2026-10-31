import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
log = logging.getLogger(__name__)
class PaperWiseError(Exception):
    def __init__(self, code, message, status=400, retryable=False, hint=None):
        self.code, self.message, self.status, self.retryable, self.hint = code,message,status,retryable,hint

def response(code, message, status, retryable=False, hint=None):
    return JSONResponse(status_code=status, content={'error':{'code':code,'message':message,'retryable':retryable,'hint':hint}})

def register_handlers(app: FastAPI):
    @app.exception_handler(PaperWiseError)
    async def paperwise_error(request: Request, exc: PaperWiseError):
        return response(exc.code, exc.message, exc.status, exc.retryable, exc.hint)
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return response('VALIDATION_ERROR', 'Invalid request.', 422, hint=str(exc.errors()[0].get('msg','Invalid input')) if exc.errors() else None)
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return response('NOT_FOUND' if exc.status_code == 404 else 'VALIDATION_ERROR', str(exc.detail), exc.status_code)
    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        log.exception('Unhandled request error')
        return response('INTERNAL', 'An internal error occurred.', 500)
