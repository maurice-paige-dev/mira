# CI/CD Pipeline — KPIs

> Covers `.github/workflows/build-deploy.yml`. The CI/CD pipeline is the quality gate for every commit to `main`. When the workflow changes, these KPIs must be reassessed.

## 1. Test Job

| KPI | Definition | Method | Target |
|---|---|---|---|
| Pass Rate | Successful runs / total runs | GitHub Actions UI | 100% on main |
| Duration | Total test job time | GitHub Actions timing | < 10 minutes |
| Coverage Threshold | `pytest --cov-fail-under` passes | CI exit code | ≥ 70% |
| Coverage Report Upload | HTML coverage report uploaded as artifact | Action step success | Always |
| Coverage Summary | Per-package coverage printed to job summary | `$GITHUB_STEP_SUMMARY` | Always |

## 2. Build & Push Job

| KPI | Definition | Method | Target |
|---|---|---|---|
| Docker Build Success | Both images build without errors | CI exit code | Always |
| Docker Push Success | Images pushed to registry | CI exit code | Always (on main) |
| Build Duration | Time from checkout to push | CI timing | < 10 minutes |
| Tag Generation | SHA and latest tags generated | `docker/metadata-action` | Both present |
| Secrets Available | DOCKER_USERNAME and DOCKER_PASSWORD set | CI variable check | Yes (on main) |

## 3. Kustomize & Manifest Step

| KPI | Definition | Method | Target |
|---|---|---|---|
| Image Tag Update | Kustomize image tags updated to new SHA | `kustomize edit set image` | Correct SHA |
| Manifest Build | `kustomize build` succeeds | CI exit code | Always |
| Manifest Upload | Final manifests uploaded as artifact | Action step success | Always |
| Manifest Retention | Artifact retention configured | `retention-days` | 30d |

## 4. Pipeline Health

| KPI | Definition | Method | Target |
|---|---|---|---|
| Failure Rate | Workflow failures per week | GitHub Actions | < 1 |
| Recovery Time | Time from failure to green build | GitHub Actions | < 1 hour |
| Secret Rotation Impact | Workflow passes after credential rotation | Manual | No downtime |

## Spec Assessment Checklist

When a spec proposes CI/CD changes:

- [ ] Do new build steps require additional secrets?
- [ ] Do new test types need longer CI timeout?
- [ ] Are coverage thresholds updated if new code is added?
- [ ] Are new artifacts documented and retained appropriately?
- [ ] Does the workflow trigger on the correct branches?
- [ ] Are Docker build contexts and Dockerfiles correct for each image?
- [ ] Is `kustomization.yaml` updated with new image names?
