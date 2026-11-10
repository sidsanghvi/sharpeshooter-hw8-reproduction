class DomainError(Exception):
    """A rejected domain action, safe to return at a transport boundary."""

    def __init__(self, code: str, message: str, details=None):
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else details


ERROR_CODES = {
    "unauthorized": "AUTH_INVALID", "forbidden": "ROLE_FORBIDDEN",
    "invalid_input": "INVALID_INPUT", "not_found": "NOT_FOUND",
    "invalid_state": "STATUS_CONFLICT", "not_claimable": "CLAIM_UNAVAILABLE",
    "invalid_claim": "CLAIM_EXPIRED",
}
HTTP_STATUS = {
    "AUTH_REQUIRED": 401, "AUTH_INVALID": 401, "ROLE_FORBIDDEN": 403,
    "SELF_REVIEW_FORBIDDEN": 403,
    "INVALID_INPUT": 422, "NOT_FOUND": 404, "EVALUATOR_FAILED": 502,
}


def error_result(exc):
    code = ERROR_CODES.get(exc.code, exc.code)
    return {"ok": False, "error": {"code": code, "message": str(exc), "details": exc.details}}


def http_status(result):
    return 200 if result["ok"] else HTTP_STATUS.get(result["error"]["code"], 409)
