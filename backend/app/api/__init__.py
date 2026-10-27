class ApiError(Exception):
    """Known failure → JSON {"detail": human message, "code": MACHINE_CODE, **extra}."""

    def __init__(self, status: int, code: str, detail: str, **extra):
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra
