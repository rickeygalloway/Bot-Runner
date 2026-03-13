Review the code changes or file specified: $ARGUMENTS

If no argument is given, review all staged and unstaged changes (`git diff HEAD`).

## What to check

### Bot contract
- `run()` is present and returns `str | None`
- No secrets or credentials hardcoded — all config comes from `core.config`
- Logger obtained via `get_logger("<bot_name>")`, not print statements or a custom logger
- Exceptions are allowed to propagate so the scheduler marks the run as `failure`

### Thread safety
- Bots run in APScheduler background threads — flag any use of shared mutable state without locking
- No `asyncio.run()` inside a bot (already used by the Telegram notifier; nesting will deadlock)

### Scheduler / config
- `config.yaml` has all required fields: `name`, `description`, `schedule`, `enabled`, `notify`
- Cron expression is valid and in UTC
- `notify.on` is one of `success` | `failure` | `always`

### General quality
- No unused imports
- No bare `except:` — catch specific exceptions or at minimum `except Exception`
- No mutable default arguments
- Log messages use loguru lazy formatting (`log.info("val={}", x)`) not f-strings

## Output format

For each issue found:
- **File:line** — severity (critical / warning / suggestion)
- One sentence describing the problem
- A suggested fix (inline code if short, otherwise a diff block)

End with a **summary line**: `X critical · Y warnings · Z suggestions`
