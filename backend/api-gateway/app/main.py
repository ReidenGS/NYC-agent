from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import settings
from app.models.common import ApiEnvelope, ApiError

app = FastAPI(title=settings.app_name, version='0.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    payload = ApiEnvelope(
        success=False,
        trace_id='trace_validation_error',
        session_id=None,
        data=None,
        error=ApiError(code='VALIDATION_ERROR', message='request validation failed', retryable=True, details={'errors': exc.errors()}),
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    # Route helpers raise HTTPException with a fully shaped envelope so the
    # frontend can always parse the same top-level contract, including errors.
    if isinstance(exc.detail, dict) and exc.detail.get('success') is False:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    payload = ApiEnvelope(
        success=False,
        trace_id='trace_http_error',
        session_id=None,
        data=None,
        error=ApiError(code='HTTP_ERROR', message=str(exc.detail), retryable=exc.status_code >= 500, details={}),
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


@app.exception_handler(Exception)
async def generic_exception_handler(_: Request, exc: Exception):
    payload = ApiEnvelope(
        success=False,
        trace_id='trace_internal_error',
        session_id=None,
        data=None,
        error=ApiError(code='INTERNAL_ERROR', message=str(exc), retryable=True, details={}),
    )
    return JSONResponse(status_code=500, content=payload.model_dump())
