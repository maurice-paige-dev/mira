# Deployment & Operation Scripts — KPIs

> Covers scripts in `scripts/` used for local development, macOS service management, and deployment. These are the bridge between code and running services.

## 1. Local Development Setup

| KPI | Definition | Method | Target |
|---|---|---|---|
| Install Success | `install-watcher.sh` completes without error | Manual run | Pass |
| Service Registration | LaunchAgent registered and loaded | `launchctl list` | com.ecommerce.ingest-watcher loaded |
| Uvicorn Start | `run.sh` starts all API processes | Manual run | catalog (8001) + chatbot (8000) listen |

## 2. macOS LaunchAgent

| KPI | Definition | Method | Target |
|---|---|---|---|
| Plist Validity | `plist` file parses correctly | `plutil -lint` | OK |
| Watch Path | Watches correct directory (`data/ingest/`) | Plist `WatchPaths` | Present |
| Process Management | Restarts on crash | Plist `KeepAlive` | Yes |
| Logging | stdout/stderr redirected to log files | Plist `StandardOutPath`/`StandardErrorPath` | Present |

## 3. Script Robustness

| KPI | Definition | Method | Target |
|---|---|---|---|
| Idempotency | Running scripts multiple times is safe | Manual review | Yes |
| Error Handling | Fails fast with clear message on missing dependencies | Code review | Yes |
| Python Environment | Scripts use `.venv` or system Python properly | Code review | Correct path |

## Spec Assessment Checklist

When a spec proposes changes in `scripts/`:

- [ ] Do new scripts check for required dependencies before running?
- [ ] Are scripts idempotent (safe to re-run)?
- [ ] Are macOS LaunchAgent plist files updated for new watcher processes?
- [ ] Are log file paths consistent and documented?
- [ ] Do scripts support both dev and production environments?
