from starlette.exceptions import HTTPException as StarletteHTTPException


class HTTPException(StarletteHTTPException):
    def __init__(self, status_code, detail=None, headers=None):
        super().__init__(status_code=status_code, detail=detail)
        self.headers = headers


class RequestValidationError(ValueError):
    def __init__(self, errors, *, body=None):
        self._errors = errors
        self.body = body
        super().__init__(errors)

    def errors(self):
        return list(self._errors)
