from fin_ai_lab.core.evals.graders.forbidden import ForbiddenGrader
from fin_ai_lab.core.evals.models import Case, GraderSpec


def _case() -> Case:
    return Case(id="c1", input={}, provenance="synthetic")


async def test_forbidden_passes_when_phrase_absent() -> None:
    grader = ForbiddenGrader(GraderSpec(type="forbidden", params={"phrases": ["kup", "sprzedaj"]}))

    result = await grader.grade(_case(), "Ekspozycja portfela wzrosła.", ctx=None)

    assert result.passed is True


async def test_forbidden_fails_when_phrase_present() -> None:
    grader = ForbiddenGrader(GraderSpec(type="forbidden", params={"phrases": ["kup"]}))

    result = await grader.grade(_case(), "Powinieneś Kup tę akcję.", ctx=None)

    assert result.passed is False
    assert "kup" in result.details["found"]


async def test_forbidden_ignores_the_phrase_inside_a_longer_word() -> None:
    grader = ForbiddenGrader(GraderSpec(type="forbidden", params={"phrases": ["kup"]}))

    result = await grader.grade(
        _case(), "Raport nie jest sugestią kupna ani sprzedaży.", ctx=None
    )

    assert result.passed is True
