from starlette.responses import JSONResponse, Response

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException


async def http_exception_handler(request, exc):
    headers = getattr(exc, "headers", None)
    if exc.status_code in (204, 304):
        return Response(status_code=exc.status_code, headers=headers)
    if headers:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


async def request_validation_exception_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})
