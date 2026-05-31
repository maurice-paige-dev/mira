# Design Specs — KPIs

> Covers all `.md` files in `specs/`. Specs govern every non-trivial change per AGENTS.md ("Specs before code"). These KPIs measure spec quality and process compliance.

## 1. Spec Completeness

| KPI | Definition | Method | Target |
|---|---|---|---|
| Required Sections | Motivation, proposed approach, key decisions, open questions, implementation plan | Manual review per AGENTS.md | All 5 present |
| Motivation Clarity | Clear description of problem being solved | Manual review | A reader unfamiliar with the project understands why |
| Key Decisions Documented | Design alternatives considered with rationale | Manual review | ≥ 2 alternatives with pros/cons |
| Open Questions | Known unknowns explicitly listed | Manual review | ≥ 1 unless trivial change |

## 2. KPI Awareness

| KPI | Definition | Method | Target |
|---|---|---|---|
| KPI Change Section | Spec includes section "KPIs Affected" listing which KPIs change | Manual review | Present |
| Prometheus Metrics | Spec identifies new metrics needed in `backend/metrics.py` | Spec review | Explicit |
| Grafana Dashboards | Spec identifies dashboard panel changes | Spec review | Explicit |
| Alerting Rules | Spec identifies new alert conditions in `prometheus-rules.yaml` | Spec review | Explicit |
| Test Coverage | Spec identifies new or updated tests | Spec review | Explicit |

## 3. Spec Lifecycle

| KPI | Definition | Method | Target |
|---|---|---|---|
| Spec-to-Implementation Lag | Time from spec approval to first commit | Git log | < 1 week |
| Spec Update Frequency | Spec updated when implementation diverges from original design | Manual | Always |
| Post-Implementation Review | Spec checked for accuracy after implementation | Manual | Yes |

## 4. Existing Specs

| Spec | Status | KPI Assessment Last Updated |
|---|---|---|
| `kafka-ingestion.md` | Implemented | Review needed |
| `agentic-chat.md` | In progress | Review after implementation |
| `observability.md` | Implemented | Review needed |
| `testing-strategy.md` | Implemented | Review needed |

## Spec Assessment Checklist

Before writing a new spec:

- [ ] Does the spec include a "KPIs Affected" section?
- [ ] Does the spec list which Prometheus metrics need updating?
- [ ] Does the spec specify which Grafana dashboards need new panels?
- [ ] Does the spec specify which alerting rules need updating?
- [ ] Does the spec identify test coverage requirements?
- [ ] Does the spec reference existing KPIs in the relevant subdirectory?
- [ ] After implementation, is the spec updated to reflect what was actually built?
