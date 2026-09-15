from fin_ai_lab.core.errors import GraderError
from fin_ai_lab.core.evals.models import Case


def get_field(output: object, field: str | None) -> object:
    if field is None:
        return output
    if isinstance(output, dict):
        return output.get(field)
    return getattr(output, field, None)


def require_expected_field(case: Case, field: str | None, grader_name: str) -> object:
    if not field or case.expected is None or field not in case.expected:
        raise GraderError(f"Grader '{grader_name}' needs expected.{field} in case '{case.id}'")
    return case.expected[field]


def to_hashable(value: object) -> object:
    if isinstance(value, dict):
        return tuple(sorted((key, to_hashable(v)) for key, v in value.items()))
    if isinstance(value, list):
        return tuple(to_hashable(v) for v in value)
    return value
