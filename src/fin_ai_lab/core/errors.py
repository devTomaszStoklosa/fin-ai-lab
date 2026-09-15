class ConfigError(Exception):
    pass


class UnknownModelError(Exception):
    pass


class ResponseValidationError(Exception):
    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response
