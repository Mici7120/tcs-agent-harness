---
name: code-review-audit
description: Perform an independent security, boundary, error-handling, and test-coverage audit on workspace changes.
---
# Code Review & Security Audit Skill

1. **Scope Diff**: Inspect modified files with `read_file` or `run_bash` (`git status` / `git diff`).
2. **Check Security & Boundaries**:
   - Path traversal or unsandboxed shell interpolation
   - Leaked secrets or tokens in logs/commits
   - Missing timeout or resource bounds on external calls
3. **Verify Tests**: Run the project's test suite and confirm edge cases are covered.
4. **Emit Verdict**: Conclude with `VERDICT: PASS` or `VERDICT: FAIL` and numbered findings citing `path:line`.
