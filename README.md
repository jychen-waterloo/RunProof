# RunProof

**Verifiable execution receipts for automation and AI agents**

> If it didn’t leave evidence, it didn’t happen.

---

## Why RunProof?

Modern automation and AI agents can *decide* a lot —
but they are surprisingly bad at **proving what they actually did**.

Common failure modes:

* An agent *claims* it saved a record, but nothing was written.
* A script partially ran, skipped a critical step, and still exited “success”.
* State is scattered across logs, files, and databases — impossible to audit.
* When something goes wrong, you cannot answer a simple question:
  **“Which step failed, and what concrete artifacts were produced?”**

Traditional observability tools help you *see* execution.

**RunProof exists to make execution *provable*.**

---

## What is RunProof?

RunProof is a lightweight execution integrity layer for automation.

It wraps your existing code and produces a **verifiable execution receipt** for every run:

* What steps ran
* Which steps were required
* What concrete evidence each step produced
* Whether the run actually satisfied its integrity conditions

RunProof does **not** prove correctness.
It proves **that execution happened and left real artifacts**.

---

## What RunProof is *not*

To avoid confusion, RunProof is **not**:

* ❌ A workflow engine
* ❌ An AI agent framework
* ❌ A logging or tracing system
* ❌ A formal verification or correctness proof tool

RunProof sits *below* agents and workflows.

It answers one question only:

> **Did this run actually do what it was supposed to do?**

---

## Core Idea: Execution Receipts

Every run produces a **receipt**.

A receipt is a structured, human-readable record containing:

* Run metadata (start, end, status)
* A list of executed steps
* For each step:

  * Whether it was required
  * Whether it succeeded
  * Verifiable evidence (rows written, files created, exit codes, hashes, etc.)

Example (simplified):

```json
{
  "run": "leetcode-session",
  "status": "failed (integrity)",
  "steps": [
    { "name": "fetch_state", "status": "success" },
    {
      "name": "write_record",
      "required": true,
      "status": "missing"
    }
  ]
}
```

If a required step did not leave evidence, the run **fails**, even if no exception occurred.

---

## Design Principles

### 1. Runs are transactions, not logs

A run either produces a complete receipt — or it fails.

Silent success is considered a bug.

---

### 2. Evidence beats text

RunProof does not trust strings like:

> “Saved successfully.”

It trusts **evidence**, such as:

* Rows inserted
* Files created
* Hashes changed
* Exit codes returned

If there is no evidence, the step did not happen.

---

### 3. Minimal surface, maximal clarity

RunProof is intentionally small:

* Single-process
* Single-machine
* Local JSON receipts
* No databases
* No SaaS dependency

It is designed to be *understood*, not hidden.

---

## A Minimal Example

```python
from runproof import run, step

@step(required=True)
def write_record(db, data):
    return {"rows_inserted": db.insert(data)}

with run("leetcode-session"):
    write_record(db, session)
```

After execution, you get a receipt:

```bash
$ runproof view receipt.json

Run: leetcode-session
Status: FAILED (integrity)

✔ write_record
  evidence: rows_inserted = 0
```

---

## Who Is This For?

RunProof is useful when **execution trust matters**:

* Automation scripts
* Data pipelines
* AI agents and tool-using LLMs
* DevOps workflows
* Research experiments
* Compliance-sensitive processes

If you have ever asked:

> “Did it actually run, or did it just say it did?”

RunProof is for you.

---

## Project Status

RunProof is an early-stage open-source project.

Current focus:

* Execution receipts
* Required-step integrity checks
* Local inspection tools

Future work will build on this foundation.

---

## License

Apache-2.0
