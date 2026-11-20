"""Readable reports preserve the three views and distinguish computed results."""


def render_report(report):
    lines = [
        "# Aethelgard research report",
        "",
        "**SYNTHETIC OFFLINE DEMONSTRATION — NOT INVESTMENT RESEARCH**"
        if report["synthetic"]
        else "Evidence-led research with conditional scenarios; forecast accuracy is unmeasured.",
        "",
        "Decision cutoff: " + report["request"]["as_of"],
        "",
        "Eligible recommendations: " + (", ".join(report["eligible_recommendations"]) or "None"),
        "",
    ]
    if report["withheld_recommendations"]:
        lines += [
            "Withheld by evidence/calculation gates: " + ", ".join(report["withheld_recommendations"]),
            "",
        ]
    lines += [
        "## Orchestrator review",
        "",
        report["final"]["artifact"]["narrative"],
        "",
        "## Deterministic comparisons",
        "",
        report["final_calculations"]["score_definition"],
        "",
        "| Horizon | Ticker | Base return | Bear return | Bull return | Conditional score |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for horizon in report["final_calculations"]["rankings"]:
        for row in horizon["ranked"]:
            lines.append(
                f"| {horizon['years']} years | {row['ticker']} | {row['base_return']:.1%} | "
                f"{row['bear_return']:.1%} | {row['bull_return']:.1%} | {row['score']:.1%} |"
            )
    lines += [
        "",
        "These are scenario outputs from supplied assumptions, not expected returns or calibrated probabilities.",
        "",
    ]
    for row in report["final_calculations"]["candidates"]:
        if row["gaps"]:
            lines += [f"**{row['ticker']} evidence gaps:** " + "; ".join(row["gaps"]), ""]
    for stage in ("independent", "self_reviews", "cross_reviews", "fresh_audits", "revisions"):
        lines += ["## " + stage.replace("_", " ").title(), ""]
        lines += [
            "Audit history only: these model drafts are not the released recommendation list. Later evidence gates may reject their conclusions.",
            "",
        ]
        for role, value in report[stage].items():
            lines += ["### " + role.title(), "", value["artifact"]["narrative"], ""]
            for finding in value["artifact"]["findings"]:
                lines += [
                    f"- **{finding['severity']} / {finding['subject']}:** {finding['explanation']} "
                    f"Correction: {finding['correction']}"
                ]
            lines.append("")
    lines += [
        "## Academic and methodological challenge",
        "",
        report["study"]["artifact"]["narrative"],
        "",
        "## Final source ledger",
        "",
    ]
    for source in report["final"]["artifact"]["evidence"]:
        lines += [
            f"- [{source['title']}]({source['url']}) — {source['kind']}; {source['access']}; "
            f"published {source['published_at']}. {source['claim']}"
        ]
    lines += [
        "",
        "Full inputs, evidence, provider citations, search actions, usage and stage fingerprints are in report.json.",
        "No orders were submitted. Demo assertions and passing arithmetic tests do not establish investment performance.",
        "",
    ]
    return "\n".join(lines)
