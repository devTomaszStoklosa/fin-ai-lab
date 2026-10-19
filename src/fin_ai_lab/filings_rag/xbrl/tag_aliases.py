# Manually maintained: SEC filers report the same financial concept under
# different XBRL tags across years (e.g. revenue moved from "Revenues" to
# "RevenueFromContractWithCustomerExcludingAssessedTax" after ASC 606 in
# 2018) and across filers (a bank or utility may use a different tag than
# a software company). Every tag below is verified present in real
# `companyfacts` data for at least one of this repo's corpus companies
# (Microsoft, Amazon, Oracle, Citigroup, NextEra Energy — 2026-09-17) — do
# not add a tag here without checking it against real data first.
#
# Ordered by which tag is more likely to be the intended concept when more
# than one is present for the same company (XbrlClient tries all of them
# and lets the observed data — not this order — decide what a period
# actually reports, since not every company uses every tag).
TAG_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
}
