# Verification record

Development date: November 20, 2026. Local environment: Windows, Python 3.12, official MCP Python SDK 2.3.

Verified: financial arithmetic and evidence gates; mocked provider refusals, malformed/incomplete output, provenance and credential checks; in-process MCP tools; complete three-worker stdio workflow; stage barriers, peer coverage, cancellation and reports; mocked SEC acceptance filtering and Alpaca pagination/partial-day handling.

No billed OpenAI research run or authenticated Alpaca retrieval was performed for implementation testing. Demo output is synthetic. Companion-chat research does not prove that this standalone live integration has been tested.

CI and test totals are recorded by the repository workflow and later commits. Tests measure software behavior, not source truth, forecast calibration or investment performance. There is no claimed out-of-sample return record.

Publication compares the remote Git tree with local files, including the full lockfile. An early truncated lockfile transfer was corrected in a dedicated commit; the restored file passed locked installation.
