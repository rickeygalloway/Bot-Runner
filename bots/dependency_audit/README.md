# dependency_audit

Weekly check of all pinned packages in `requirements.txt` against their latest versions on PyPI. Claude summarises what's outdated and flags known security or deprecation concerns.

## How it works

1. Parses `requirements.txt` for all `package==version` pins
2. Queries the PyPI JSON API for the latest stable release of each package
3. Builds a comparison table (pinned vs latest)
4. Sends to Claude for a grouped audit report

## Output format

```
## Dependency Audit

### Up to date
- fastapi 0.111.0

### Outdated
- anthropic 0.40.0 → 0.52.0 [MINOR] — several new API features added

### Security / deprecation concerns
- ...

### Summary
...
```

## Required env vars

```
ANTHROPIC_API_KEY=
```

## Schedule

Every Monday at 09:00 UTC (`0 9 * * 1`).
