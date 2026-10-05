"""Custom exceptions for the design app."""


class DesignError(Exception):
    """Base exception for design app errors."""


class EvaluationError(DesignError):
    """Mass evaluation failed."""

    def __init__(self, message: str, design_id: int | None = None):
        self.design_id = design_id
        super().__init__(message)


class ConvergenceError(DesignError):
    """GA optimization failed to converge."""

    def __init__(self, message: str, generation: int = 0):
        self.generation = generation
        super().__init__(message)


class SiteGeometryError(DesignError):
    """Site polygon processing failed."""

    def __init__(self, message: str, pnu: str = ""):
        self.pnu = pnu
        super().__init__(message)
