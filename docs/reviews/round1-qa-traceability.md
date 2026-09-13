# Round 1 QA / TDD / Traceability Review

Review date: 2026-09-13 (Asia/Taipei)

Review scope: `docs/product-requirements.md`, `docs/software-design.md`, `docs/test-driven-development.md`, `docs/implementation-plan.md`, `docs/research/*.md`, existing `tests/`, `pyproject.toml`, and `.github/workflows/test.yml`.

Review stance: independent read-only review. No product/design/test-plan body file was modified.

## Outcome

**NEEDS REVISION before implementation-ready approval.** All 22 PRD acceptance IDs are mentioned in the TDD traceability matrix, and the existing sample-only baseline is healthy. However, several public contracts contradict each other, release gate IDs are overloaded, planned rule assets cannot currently reach an installed wheel, and the proposed gate evidence is not yet machine-verifiable.

Severity meaning:

| Severity | Meaning |
| --- | --- |
| High | Can produce incompatible implementations, incorrectly enable an official source, or make a required P1.1 acceptance criterion impossible to satisfy. |
| Medium | Does not immediately corrupt data, but prevents deterministic QA, repeatable release evidence, or consistent review. |
| Low | Editorial or maintainability issue with a contained effect. |

## Verified baseline

| Check | Result | Interpretation |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe -m pytest -q` | `53 passed in 3.06s` | Existing sample-only baseline is green; this is not evidence for official mode. |
| `.\.venv\Scripts\python.exe -m ruff check .` | Passed | Current Python files pass the configured lint rules. |
| `.\.venv\Scripts\python.exe -m ruff format --check src tests` | `17 files already formatted` | Current source and tests satisfy the CI format check. |
| `.\.venv\Scripts\python.exe -m build` | sdist and wheel built successfully | Current 0.1.1 package builds. |
| `lit.cmd --version` | `2.0.0` | The reviewed machine has LiteParse, but the CDC qualification workflow is not yet pinned or encoded in CI/release commands. |

Two commands documented as standard focused checks are not runnable against the current tree:

```text
.\.venv\Scripts\python.exe -m pytest -q tests\test_nhi_importer.py
=> ERROR: file or directory not found (exit 1)

.\.venv\Scripts\python.exe -m pytest -q -k 'publish or stale or fail_closed'
=> 53 deselected (exit 1)
```

## Acceptance coverage audit

Textual coverage is complete: `CDC-01..05`, `NHI-01..05`, `TFDA-01..05`, `LAB-01..05`, and `UX-01..03` all occur in the TDD matrix. All 11 SDD IDs also occur in the TDD document.

This is **mention coverage**, not executable traceability. The matrix does not identify a test file/node ID, golden case ID, evidence artifact, or pass/fail source for any acceptance criterion. Grouped rows such as `CDC-01, CDC-02` and `TFDA-02, TFDA-03` also prevent independently closing one criterion while leaving the other open.

## Findings

### QA-01 — High — Validation and review status contracts conflict

**Files/lines:** `docs/product-requirements.md:125-136`, `docs/software-design.md:232-244`, `docs/software-design.md:466-483`.

**Evidence:** The PRD defines `validation_status=approved|review_pending|rejected`. The SDD manifest uses `validation.status=passed` plus a separate `review.status=approved`, while `ToolResult v2` permits `sample|passed|review_pending|unavailable` and omits `rejected`. The example manifest is internally inconsistent: `required_gates` contains `source` and `schema`, but `completed` contains only `source` while review status and snapshot state are already `approved`.

**Impact:** Different implementations can serialize incompatible statuses, and a validator following the example could publish a snapshot with an incomplete required gate.

**Minimum correction:** Define separate, non-overlapping enums for automatic validation, human review, pipeline state, availability, and query result. Add the exact mapping to ToolResult. Correct the manifest example so `approved` requires set equality between required and completed gates, with every completed record bound to artifact/rule hashes.

### QA-02 — High — `G1`–`G5` are reused for two different gate systems

**Files/lines:** `docs/product-requirements.md:154-164`, `docs/software-design.md:450-462`, `docs/test-driven-development.md:295-309`, `docs/research/cdc-data-source.md:110-120`.

**Evidence:** PRD `G1` means common data safety and `G5` means user pilot acceptance. CDC research and the SDD reuse `G1` for source/artifact review and `G5` for owner publish. The TDD document explicitly says it uses only the PRD `G1`–`G5` numbering.

**Impact:** A review record saying “G5 passed” cannot be interpreted reliably; owner publish could be mistaken for completed user acceptance.

**Minimum correction:** Reserve `G1`–`G5` exclusively for PRD release gates. Rename source-local gates to stable names such as `CDC-SOURCE`, `CDC-LAYOUT`, `CDC-CONTENT`, `CDC-LAB`, and `OWNER-PUBLISH`, then provide a mapping from each local gate to PRD `G1`–`G5`.

### QA-03 — High — Required NHI `as_of` behavior is deferred by the SDD

**Files/lines:** `docs/product-requirements.md:87-91`, `docs/software-design.md:374-381`, `docs/software-design.md:592-596`, `docs/test-driven-development.md:62-65`.

**Evidence:** `NHI-04` requires an `as_of` input and specific historical-unavailable behavior. The SDD says “`as_of` 若未來加入” and Phase 1 only commits to `get_points` exact lookup. TDD nevertheless treats `NHI-04` as a P1.1 test target.

**Impact:** P1.1 cannot satisfy its own required acceptance criterion with the designed API.

**Minimum correction:** Either add `as_of` as an optional P1.1 `get_points` parameter with exact response semantics and stdio tests, or explicitly move `NHI-04` to a later version and revise the PRD completion definition.

### QA-04 — High — NHI candidate search and alias behavior are not a single implementable contract

**Files/lines:** `docs/product-requirements.md:87-91`, `docs/software-design.md:359-381`, `docs/test-driven-development.md:62-65`, `docs/test-driven-development.md:140-146`.

**Evidence:** `NHI-02` requires Chinese/English/alias search to return all matching candidates and show scope status even before the allowlist is approved. The SDD says `search_lab_code` and `get_payment_rule` return `scope_review_pending`, or candidates may be exposed through a future new tool. No alias table, alias provenance, review state, or versioning contract is defined.

**Impact:** One implementation may return candidates and another may return only an error/status, yet both could claim conformance. Unproven aliases could also affect retrieval silently.

**Minimum correction:** Choose one P1.1 behavior. If candidates are returned, define candidate-only status/warning, alias schema/provenance/rule version, deterministic ordering, and tests. If no candidates are returned before approval, revise `NHI-02` accordingly.

### QA-05 — High — TFDA IVD search inclusion rules contradict the PRD

**Files/lines:** `docs/product-requirements.md:95-101`, `docs/software-design.md:398-418`, `docs/test-driven-development.md:66-68`, `docs/test-driven-development.md:158-165`.

**Evidence:** `TFDA-04` says every IVD search result can carry `included`, `ambiguous`, or `unknown`. The SDD says `search_ivd` returns only `ivd_included`; ambiguous/unknown states are available through other behavior such as `get_license` or review candidates.

**Impact:** Recall, warning, and safety behavior for the primary IVD search tool are undefined, and the same golden case can have incompatible expected outcomes.

**Minimum correction:** Define an explicit search matrix by tool and filter: which states may be returned, default state filter, status when only candidate matches exist, and whether candidate keyword recall is exposed. Align the PRD acceptance text and TDD node IDs to that matrix.

### QA-06 — High — Versioned rule assets are outside the installed package

**Files/lines:** `docs/software-design.md:138-149`, `docs/software-design.md:555-581`, `docs/test-driven-development.md:271-273`, `pyproject.toml:19-27`.

**Evidence:** The SDD locates schemas, NHI scope rules, and TFDA IVD rules under top-level `rules/**`. The wheel configuration includes only `src/taiwan_lab_mcp`. Inspection of the built wheel confirms that only package code and bundled sample JSON are present; no top-level rules are installed. Yet release acceptance requires official installed-wheel stdio and a data CLI outside the repository.

**Impact:** An installed official importer/runtime cannot reliably locate the exact schema/rule version needed to validate or explain a snapshot.

**Minimum correction:** Put immutable rule/schema resources under the Python package and load them with `importlib.resources`, or explicitly copy a hash-bound rule bundle into each data root/snapshot during sync. Add an out-of-tree wheel test that runs the data CLI and resolves a rule without repository access.

### QA-07 — Medium — The traceability matrix and test filenames are not executable

**Files/lines:** `docs/test-driven-development.md:54-78`, `docs/test-driven-development.md:235-269`, `docs/software-design.md:575-581`.

**Evidence:** The TDD matrix contains prose rather than exact pytest node IDs or evidence artifact paths. SDD and TDD name the same planned tests differently (`test_import_nhi.py` versus `test_nhi_importer.py`, `test_snapshot.py` versus `test_snapshot_publish.py`, and `test_official_stdio.py` versus `test_mcp_stdio.py`/`test_official_adapters.py`). The documented NHI and `-k` commands currently exit 1.

**Impact:** Developers cannot follow one canonical test layout, and release reviewers cannot deterministically calculate acceptance coverage.

**Minimum correction:** Choose one filename set. Give every PRD ID its own matrix row with exact pytest node IDs, golden case IDs, evidence path, and responsible gate. Label future commands as unavailable until their files exist, while keeping the current 53-test baseline command separate.

### QA-08 — High — CDC full-source qualification has no reproducible command or environment contract

**Files/lines:** `docs/software-design.md:420-436`, `docs/software-design.md:603-606`, `docs/test-driven-development.md:167-181`, `.github/workflows/test.yml:38-53`, `pyproject.toml:10-13`.

**Evidence:** The SDD requires a 130/29-page LiteParse spike and the TDD moves full-PDF extraction to a “source qualification job,” but neither document defines the command, input location, pinned LiteParse version/checksum, output schema, expected report, or CI/manual workflow that runs it. The existing CI only runs Python lint/test/build. The SDD also calls the current full PDFs a fixture while its fixture rule says checked-in fixtures must be small and synthetic.

**Impact:** `SDD-CDC-01` and CDC `G2/G3` cannot be reproduced by a second reviewer, and full official PDFs could be accidentally treated as ordinary checked-in fixtures.

**Minimum correction:** Define one explicit local qualification command with a required LiteParse version, `--no-ocr` options, raw-artifact hash input, output layout schema/version, review report path, and exit codes. Keep full official artifacts under ignored `data/raw`; CI should use minimal synthetic layout fixtures and must not claim that they qualify a production PDF.

### QA-09 — Medium — Golden/review evidence lacks a machine-enforced approval schema

**Files/lines:** `docs/product-requirements.md:146-162`, `docs/software-design.md:182-263`, `docs/test-driven-development.md:192-221`, `docs/implementation-plan.md:218-220`.

**Evidence:** The TDD lists desired golden fields, but no canonical JSON schema/Pydantic model, `extra=forbid` rule, approved-status predicate, test command, or report format is defined. `raw_artifact_sha256` is optional, while the release gate demands official locator verification. “At least 10” can therefore be counted differently, and a synthetic fixture plus copied expected official values could be mistaken for official parser qualification.

**Impact:** G2/G3 may appear green without proving that cases are bound to the reviewed artifact and active parser/schema/rule versions.

**Minimum correction:** Define a versioned golden-case model and qualification report. A countable approved case must bind the exact input fixture/raw artifact hash, expected fields, locator, parser/schema/rule versions, reviewer identity/time/status, and source ID. Separate `synthetic_ci_passed` from `official_qualification_approved` in reports.

### QA-10 — Medium — G5 pilot acceptance is measurable but not reproducible

**Files/lines:** `docs/product-requirements.md:142-152`, `docs/product-requirements.md:160-164`, `docs/test-driven-development.md:72-74`, `docs/test-driven-development.md:299-305`.

**Evidence:** Percent targets are defined, but the required tasks, scoring rubric, treatment of partial completion, warning-comprehension questions, critical-safety classification, consent text, minimal retained fields, evidence path, and sign-off owner are absent.

**Impact:** Two pilot facilitators can produce different pass/fail decisions from the same participant behavior, and G5 cannot be audited later.

**Minimum correction:** Add a short versioned pilot protocol and result schema containing task IDs, objective scoring, denominators, critical issue definition, privacy-safe fields, and an approval record. Bind the protocol/result hash into release evidence.

### QA-11 — Medium — NHI date parsing differs between the implementation plan and verified source contract

**Files/lines:** `docs/implementation-plan.md:117-125`, `docs/research/nhi-data-source.md:104-112`, `docs/software-design.md:347-372`, `docs/test-driven-development.md:131-138`.

**Evidence:** The implementation plan says to preserve and convert “民國／西元日期.” The verified source research, SDD, and TDD all require strict eight-digit Gregorian `YYYYMMDD` and explicitly say not to apply ROC conversion.

**Impact:** An implementer following the plan could introduce an unnecessary second parser or corrupt dates by guessing calendar systems.

**Minimum correction:** Replace the implementation-plan rule with strict Gregorian `YYYYMMDD`, raw preservation, ISO derived value, and no ROC conversion unless a future source-specific schema explicitly introduces it.

### QA-12 — Medium — Release archive safety is a promise without a CI check

**Files/lines:** `docs/test-driven-development.md:295-309`, `.github/workflows/test.yml:46-53`, `pyproject.toml:22-27`.

**Evidence:** TDD requires wheel/sdist archives to exclude raw, staged, quarantine, temporary reports, and secrets. Current CI builds and installs the wheel but never enumerates or asserts archive contents. The current wheel was manually inspected and is clean, but that one observation does not prevent future packaging drift.

**Impact:** A future include rule or package-data change can leak official raw artifacts, review reports, local paths, or secrets while all current CI steps remain green.

**Minimum correction:** Add a cross-platform archive-content test after build. Enumerate both wheel and sdist; fail on denylisted roots/patterns and secret-like filenames; separately allowlist intended package resources. Save the inventory as release evidence.

## Release readiness decision

The documents are strong enough to guide a second revision, but not yet to authorize implementation as a stable contract. Minimum round-1 exit criteria are:

1. Resolve QA-01 through QA-06 so product/API/gate behavior is singular.
2. Make the matrix node-level and unify filenames/commands (QA-07).
3. Define reproducible CDC and golden qualification artifacts (QA-08, QA-09).
4. Make G5 and archive inspection auditable (QA-10, QA-12).
5. Align the NHI date rule (QA-11).

After those corrections, rerun this review against exact line-level changes and execute the current baseline plus every newly documented focused command.
