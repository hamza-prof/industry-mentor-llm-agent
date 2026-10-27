class ApiError(Exception):
    """Known failure → JSON {"detail": human message, "code": MACHINE_CODE} with an HTTP status."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail
