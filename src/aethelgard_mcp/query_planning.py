"""Inspectable query expansion driven by request context and unresolved evidence."""

from .models import ResearchRequest


def plan_queries(request: ResearchRequest, gaps: list[str] | None = None) -> dict:
    day, year = request.as_of.date().isoformat(), request.as_of.year
    batches = [
        {
            "purpose": "macro regime and competing explanations",
            "queries": [
                f"Federal Reserve policy statement inflation credit conditions {day}",
                f"Treasury yield curve corporate credit spreads {day}",
                f"stock market selloff rally sector earnings valuation {day}",
                f"AI data center power supply financing customer commitments {year}",
            ],
        }
    ]
    if not request.tickers:
        batches.append(
            {
                "purpose": "dynamic discovery, not a fixed watchlist",
                "queries": [
                    f"profitable growth companies free cash flow valuation earnings {day}",
                    f"value stocks return on invested capital balance sheet {year}",
                    f"semiconductor software payments industrial market leaders earnings {year}",
                    f"small mid cap profitable companies cash generation dilution {year}",
                ],
            }
        )
    for ticker in request.tickers:
        batches.append(
            {
                "purpose": f"{ticker}: primary economics and adversarial news",
                "queries": [
                    f"{ticker} investor relations {year} quarterly earnings guidance transcript",
                    f"{ticker} site:sec.gov/Archives/edgar/data 10-Q 10-K {year}",
                    f"{ticker} last completed session closing price as of {day}",
                    f"{ticker} debt rating cash flow stock compensation commitments {year}",
                    f"{ticker} investigation lawsuit acquisition customer loss {day}",
                ],
            }
        )
    if gaps:
        batches.append(
            {
                "purpose": "unresolved evidence; search variants before concluding unavailable",
                "queries": [f"{gap[:250]} {day}" for gap in gaps[:12]],
            }
        )
    return {
        "batches": batches,
        "execution_rules": [
            "These are starting queries, not executed searches or exhaustive coverage.",
            "Open articles and follow named primary sources; vary legal entity and fiscal period.",
            "Record failed queries, publication/event dates, actual access and document version.",
            "Verify publication timestamps; a date word in a query does not enforce the cutoff.",
            "Stop expanding when the decisive gap is resolved; preserve unresolved gaps explicitly.",
            "Research academic methods only at the study stage after independent and cross-review stages.",
        ],
    }
