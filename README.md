# RunProof

**Verifiable execution receipts for automation and AI agents**

> If it didn’t leave evidence, it didn’t happen.

---

## Why RunProof?

Modern automation and AI agents can execute complex workflows.
But when something goes wrong, one question is surprisingly hard to answer:

> Did it actually do what it claimed to do?

Traditional logging tells you *what was printed*.
Observability tells you *what was traced*.
But neither guarantees:

* Required steps actually ran
* External state changed as expected
* The run left measurable artifacts

RunProof introduces **execution receipts with integrity checks and side-effect verification**.

---

# What RunProof Proves (and What It Doesn’t)

RunProof distinguishes between two kinds of proof:

## 1 Execution Proof

Execution proof answers:

> Did this step run?

Each step records:

* Entry & exit
* Duration
* Status
* Errors (if any)

Required steps define **run integrity**.
If a required step did not successfully execute, the run is marked:

```
integrity_failed
```

This prevents silent partial execution.

---

## 2 Side-effect Verification (State Proof)

Execution alone is not enough.

A function can return:

```python
return {"rows_inserted": 1}
```

But did the database actually change?

To address this, RunProof introduces **Evidence Probes**.

Probes independently measure external state changes before and after a step:

* Files
* Databases
* HTTP responses
* System commands

This produces **measured evidence**, distinct from developer-reported values.

---

# Evidence Model

Each step may contain two types of evidence:

### Reported Evidence

Returned directly by the wrapped function.

Example:

```json
{
  "rows_inserted": 1
}
```

This is useful but not authoritative.

---

### Measured Evidence (via Probes)

Captured independently by RunProof.

Example (FileProbe):

```json
{
  "file": "output.txt",
  "before": {"exists": false},
  "after": {
    "exists": true,
    "size": 1024,
    "mtime": "..."
  }
}
```

Measured evidence provides stronger guarantees.

---

# Evidence Levels

Not all steps require the same verification strength.

RunProof supports configurable Evidence Levels:

### Level 0 — Reported Only

* Records execution metadata
* Stores reported return values
* Lowest overhead

### Level 1 — Light Verification (Default for Probes)

* File existence
* File size / mtime
* DB row count
* Command exit code

Balanced performance and assurance.

### Level 2 — Strict Verification

* Cryptographic file hash (e.g. SHA256)
* Stronger consistency checks

Higher cost, stronger guarantee.

*(Future roadmap may include tamper-evident receipts.)*

---

# FileProbe (First Built-in Probe)

The first built-in probe is `FileProbe`.

It verifies file system side effects:

* File existence
* Size
* Modification time
* Optional hash (strict mode)

Example:

```python
from runproof import run, exec, FileProbe

with run("file-demo"):
    exec(
        ["cp", "a.txt", "b.txt"],
        probes=[
            FileProbe("b.txt", level=1)
        ],
        required=True,
    )
```

Receipt excerpt:

```json
{
  "step": "exec: cp",
  "status": "success",
  "measured_evidence": {
    "FileProbe": {
      "before": {"exists": false},
      "after": {
        "exists": true,
        "size": 12
      }
    }
  }
}
```

If the file does not appear, the discrepancy is visible in the receipt.

---

# Integrity Model

Run status priority:

```
integrity_failed > failed > success
```

A run fails integrity if:

* Any required step never successfully executed.

This protects against:

* Silent partial runs
* Early returns
* Conditional skip errors

---

# Threat Model & Boundaries

RunProof does **not**:

* Prove program correctness
* Prevent malicious code from fabricating return values
* Monitor operations outside its execution gates

RunProof can only prove what passes through its execution wrappers.

However, by combining:

* Structured execution receipts
* Required-step integrity
* Independent side-effect probes

It significantly raises the trust level of automation workflows.

---

# Roadmap

v0.1

* Execution receipts
* Required-step integrity
* Command execution wrapper
* Evidence truncation safeguards

v0.2

* FileProbe
* Evidence Levels
* Measured vs Reported evidence separation

v0.3+

* DBProbe
* HTTPProbe
* Tamper-evident receipts
* Run index & inspection tooling

---

# Summary

RunProof moves automation from:

> “It probably ran.”

to

> “It ran, and here is the evidence.”
> 
---

## License

Apache-2.0
