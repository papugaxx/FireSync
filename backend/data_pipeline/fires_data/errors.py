class PipelineError(Exception):
    """An actionable error whose text is safe to show without credentials."""


class ConfigurationError(PipelineError):
    pass


class ProtocolError(PipelineError):
    pass


class NetworkError(PipelineError):
    pass


class QuotaError(NetworkError):
    pass


class StorageError(PipelineError):
    pass
