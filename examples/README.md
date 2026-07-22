# Hermes Exec Fuse examples

These payloads illustrate the arguments the model sends to the `exec_fuse` tool. They are documentation examples, not standalone shell scripts.

## Files

- [`repo-inspection.json`](repo-inspection.json) — four independent read-only repository inspections that may run concurrently and be cached.
- [`dependency-chain.json`](dependency-chain.json) — a mutating generation step followed by ordered read-only inspections.

## Using an example

Ask Hermes to call `exec_fuse` with the JSON object from the selected file, or use it as a template when writing a prompt.

```text
Use exec_fuse with the repository-inspection example. Keep the result compact and summarize only actionable findings.
```

## Adapting examples safely

- Keep command IDs short and unique.
- Use `depends_on` whenever ordering matters.
- Disable cache with `"cache": false` when a fresh read is required.
- Do not assume a command is read-only merely because it looks harmless; the conservative classifier is authoritative.
- Interactive and background commands are not supported.
