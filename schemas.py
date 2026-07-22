"""LLM-facing tool schemas for Hermes Exec Fuse."""

EXEC_FUSE = {
    "name": "exec_fuse",
    "description": (
        "Run one to 24 foreground shell commands in a single Hermes tool call. "
        "Prefer this tool when two or more repository inspections can be grouped. "
        "Commands classified as read-only may run concurrently and reuse exact safe results; "
        "mutating or unknown commands run sequentially and invalidate cached workspace reads. "
        "Use depends_on for required ordering. Do not use this tool for interactive or background processes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "description": (
                    "Foreground commands to execute. Each command needs a unique id; use depends_on "
                    "when one command requires another command to finish successfully first."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Short unique identifier used in dependencies and returned results.",
                        },
                        "command": {
                            "type": "string",
                            "description": "Foreground shell command delegated through Hermes' terminal tool.",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Optional working directory for this command.",
                        },
                        "timeout": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 600,
                            "description": "Optional foreground timeout in seconds.",
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command IDs that must complete successfully before this command runs.",
                        },
                        "cache": {
                            "type": "boolean",
                            "description": (
                                "Allow result reuse when this command is classified as read-only. "
                                "Set false when a fresh inspection is required. Default true."
                            ),
                        },
                    },
                    "required": ["id", "command"],
                },
            },
            "parallel": {
                "type": "boolean",
                "description": (
                    "Run ready read-only commands concurrently, with at most eight workers. "
                    "Mutating and unknown commands remain sequential. Default true."
                ),
            },
            "cache": {
                "type": "boolean",
                "description": "Enable session-scoped reuse for eligible read-only commands. Default true.",
            },
            "fail_fast": {
                "type": "boolean",
                "description": (
                    "Skip later ready commands after a failure. Commands with a failed dependency are always skipped. "
                    "Default false."
                ),
            },
            "max_output_chars": {
                "type": "integer",
                "minimum": 500,
                "maximum": 20000,
                "description": (
                    "Maximum compact output retained per command. Important diagnostic lines are prioritized. "
                    "Default 4000."
                ),
            },
        },
        "required": ["commands"],
    },
}

EXEC_FUSE_STATS = {
    "name": "exec_fuse_stats",
    "description": (
        "Return Hermes Exec Fuse metrics for the current task/session: workspace generation, active cache entries, "
        "executions, cache hits, normalized duplicate hits, avoided terminal calls, and estimated characters saved."
    ),
    "parameters": {"type": "object", "properties": {}},
}
