# Verification record

Development date: November 20, 2026. Local environment: Windows, Python 3.12, official MCP Python SDK 2.3.

The latest-quote adapter adds 21 mocked checks covering field validity, missing symbols, quote age, clock tolerance, source errors and MCP exposure. The complete current suite passes **160 tests**, lint and distribution build. IEX is explicitly one venue, and latest quotes are kept separate from historical research cutoffs. No authenticated standalone adapter call is implied by these tests.

The funded-cash update at `de213b69c41929b4be75189f8d532c0c6a27508d` passed **139 tests**, lint and distribution build, followed by [successful CI](https://github.com/DaniyalHayat/aethelgard-mcp_v0/actions/runs/44753353928). A fresh cash-model review then identified that cash minority/preferred distributions cannot be described as attributable accounting earnings. The output names now explicitly say cash-equivalent income and earnings per share; the targeted 11 cash tests pass after that correction.

Commit `50a67737613c0c22ce3b7408b23e9001f02f316e` passed 127 local tests, distribution build and [Windows/Linux CI](https://github.com/DaniyalHayat/aethelgard-mcp_v0/actions/runs/44750336134). The independent code review found and corrected audit-finding loss, unsafe released prose, assumption-based evidence, Windows hash mismatch, immediate cancellation, future observations, zero-EPS reconciliation and credential exposure before persistence. Follow-up scope tests distinguish a global finding from the valid ticker ALL and keep an excluded ticker's block from contaminating unrelated candidates.

Verified: financial arithmetic and evidence gates; mocked provider refusals, malformed/incomplete output, provenance and credential checks; in-process MCP tools; complete three-worker stdio workflow; stage barriers, peer coverage, cancellation and reports; mocked SEC acceptance filtering and Alpaca pagination/partial-day handling.

No billed OpenAI research run or authenticated Alpaca retrieval was performed for implementation testing. Demo output is synthetic. Companion-chat research does not prove that this standalone live integration has been tested.

CI and test totals are recorded by the repository workflow and later commits. Tests measure software behavior, not source truth, forecast calibration or investment performance. There is no claimed out-of-sample return record.

Publication compares the remote Git tree with local files, including the full lockfile. An early truncated lockfile transfer was corrected in a dedicated commit; the restored file passed locked installation.
