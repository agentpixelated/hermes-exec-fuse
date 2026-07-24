# Security policy

Hermes Exec Fuse sits between an LLM and a terminal tool, so classification, caching, invalidation, result-normalization, configuration, and dispatch-boundary bugs can have security consequences.

## Supported versions

The project is currently alpha software.

| Version | Support |
| --- | --- |
| `0.2.x` | Best-effort security fixes |
| `0.1.x` | Critical fixes only |
| Earlier or unpublished builds | Not supported |

There is no guaranteed response-time SLA during the alpha phase.

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue, pull request, discussion, or social post before a fix is available.

Use GitHub's private vulnerability-reporting or security-advisory feature for this repository when available. Otherwise, contact the repository owner privately through their GitHub profile and include only enough information to establish a secure reporting channel.

A useful report includes:

- affected version or commit;
- operating system and Hermes version;
- terminal backend, when relevant;
- active `HERMES_EXEC_FUSE_*` configuration without secrets;
- minimal reproduction steps;
- expected and observed behavior;
- impact assessment;
- suggested mitigation, if known.

Do not include real secrets, production credentials, or private terminal output. Use synthetic data in reproductions.

## High-priority issue classes

Reports are especially valuable when they involve:

- a mutating command incorrectly classified as read-only;
- unsafe parallel execution;
- stale cache reuse after a workspace mutation;
- a failed terminal result incorrectly treated as successful;
- a command path that bypasses `ctx.dispatch_tool("terminal", ...)`;
- shell quoting or working-directory injection;
- cross-session cache leakage;
- sensitive output exposure through cache or metrics;
- unbounded state, output, dependencies, or concurrency;
- a hook failure that disrupts the parent Hermes process.

## Security model boundaries

Hermes Exec Fuse does not sandbox commands itself. It relies on Hermes' terminal tool, approval model, configured backend, operating-system permissions, and user environment.

The classifier is a performance and stale-data safeguard, not an authorization system. Commands classified as `unknown` remain executable through Hermes and are governed by Hermes' normal security controls.

Result normalization deliberately interprets structured backend fields only. It does not scan ordinary output text for failure keywords.

Cached compact output is held in process memory and may contain terminal data. Avoid commands that expose secrets and configure Hermes' redaction and execution policies appropriately.

## Disclosure process

After a report is validated, the intended process is:

1. reproduce and assess impact;
2. prepare a focused fix and regression tests;
3. document affected versions and mitigations;
4. publish the fix before detailed public disclosure;
5. credit the reporter unless anonymity is requested.
