"""P5's public surface for other projects (docs/ARCHITECTURE.md rule 6):
the web app's "Analiza AI" imports these names from here, never from P5's
internal modules."""

from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import CommitteeReport, ComparisonReport
from fin_ai_lab.investment_committee.qa_target import compare_committee_vs_single
from fin_ai_lab.investment_committee.single_agent import run_single_agent
from fin_ai_lab.investment_committee.supervisor import run_committee

__all__ = [
    "BudgetGuard",
    "CommitteeReport",
    "ComparisonReport",
    "compare_committee_vs_single",
    "run_committee",
    "run_single_agent",
]
