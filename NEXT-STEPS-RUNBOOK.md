# Next Steps Runbook: Serverless LLM DevOps Project

## Current Implementation Status

This repository is implemented as a complete scaffold for your portfolio project.

Implemented components:
- FastAPI LLM wrapper with `/chat`, `/health`, `/metrics`
- Async Ollama integration and error handling
- Prometheus metrics instrumentation
- Multi-stage non-root Docker image
- Local docker-compose stack (Ollama + API + Prometheus + Grafana)
- Jenkins declarative pipeline (test -> build -> push -> deploy -> notify)
- AI DevOps bot (Ollama log analysis -> Discord embed)
- Kubernetes manifests (Deployment with Ollama sidecar, Services, KEDA ScaledObject, Ingress)
- Monitoring artifacts (Prometheus values and Grafana dashboard JSON)
- Main project README

What is still needed now:
- Install tools and verify environment
- Run local tests and local stack
- Deploy to Minikube and validate KEDA behavior
- Configure Jenkins credentials and run full CI/CD
- Validate monitoring and bot notifications end-to-end

## Zero-Skip Execution Plan

Follow this in exact order.

## Phase 0: Tooling Verification

Run these commands in PowerShell:

```powershell
docker --version
minikube version
kubectl version --client
helm version
python --version
```

Acceptance checks:
- Docker command works
- Minikube command works
- kubectl works
- Helm works
- Python is 3.11+

If Python is not 3.11+, install Python 3.11 and ensure `python --version` shows 3.11.x.

## Phase 1: Python Environment and Unit Tests

From repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r .\app\requirements.txt
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest .\app\tests -q
```

Acceptance checks:
- All tests pass
- No import errors

If tests fail due to module path issues, run from `app` directory exactly as shown.

If PowerShell says `pytest` command not found, always use `.\.venv\Scripts\python.exe -m pytest ...`.

## Phase 2: Local Stack with Docker Compose

Build and start:

```powershell
docker compose up -d --build
```

If `docker` is not recognized:
1. Install Docker Desktop from https://www.docker.com/products/docker-desktop/
2. Open Docker Desktop once and wait for `Engine running`.
3. Close and reopen PowerShell.
4. Verify:

```powershell
docker --version
docker compose version
```

If still failing, add `C:\Program Files\Docker\Docker\resources\bin` to your system `Path`, then open a new terminal and verify again.

Wait until containers are healthy, then pull model in Ollama container:

```powershell
docker exec -it ollama ollama pull tinyllama
```

Functional checks:

```powershell
Invoke-RestMethod -Method GET -Uri "http://localhost:8000/health"
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/chat" -ContentType "application/json" -Body '{"prompt":"Hello from portfolio demo","model":"tinyllama"}'
Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/metrics"
```

If you want to use real curl in PowerShell, call `curl.exe` instead of `curl`.

Open UIs:
- API docs: http://localhost:8000/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

Acceptance checks:
- `/health` returns status ok
- `/chat` returns a model response
- `/metrics` includes `http_requests_total`

## Phase 3: DockerHub Push Dry Run (Manual)

Set your repo and build locally first:

```powershell
$env:DOCKERHUB_REPO="ullas911/serverless-llm"
docker build -t "${env:DOCKERHUB_REPO}:local-test" .\app
docker tag "${env:DOCKERHUB_REPO}:local-test" "${env:DOCKERHUB_REPO}:latest"
```

Login and push:

```powershell
docker login
docker push "${env:DOCKERHUB_REPO}:local-test"
docker push "${env:DOCKERHUB_REPO}:latest"
```

Acceptance checks:
- Image appears in DockerHub under `ullas911/serverless-llm`

## Phase 4: Minikube + Kubernetes Deploy

Start cluster:

```powershell
minikube start
kubectl get nodes
```

Apply manifests:

```powershell
kubectl apply -f .\k8s\deployment.yaml
kubectl apply -f .\k8s\service.yaml
kubectl apply -f .\k8s\ingress.yaml
```

Note: apply `.\k8s\hpa.yaml` only after KEDA is installed in Phase 5.

Watch rollout:

```powershell
kubectl get pods -w
kubectl get deploy serverless-llm
kubectl describe deploy serverless-llm
```

Access service externally:

```powershell
minikube service serverless-llm-nodeport --url
```

Windows + Docker driver note:
- If Minikube prints `the terminal needs to be open to run it` and does not give a usable URL, use port-forward instead.
- Keep the port-forward terminal open while testing.

```powershell
kubectl port-forward svc/serverless-llm-nodeport 8000:8000
```

Use the returned URL for test call:

```powershell
Invoke-RestMethod -Method POST -Uri "<NODEPORT_URL>/chat" -ContentType "application/json" -Body '{"prompt":"test from k8s","model":"tinyllama"}'
```

If using port-forward, test with:

```powershell
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/chat" -ContentType "application/json" -Body '{"prompt":"test from k8s","model":"tinyllama"}'
```

Acceptance checks:
- Pod starts with both containers (`llm-api`, `ollama`)
- InitContainer successfully pulls model
- Chat endpoint works via NodePort URL

## Phase 5: KEDA Installation and Scale-to-Zero Validation

Install KEDA:

```powershell
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace
```

Optional HTTP add-on:

```powershell
helm install keda-http-add-on kedacore/keda-add-ons-http --namespace keda
```

Re-apply ScaledObject:

```powershell
kubectl apply -f .\k8s\hpa.yaml
kubectl get scaledobject
kubectl describe scaledobject serverless-llm-scaledobject
```

Validate scale-to-zero behavior:
1. Stop generating traffic for ~2-3 minutes.
2. Watch deployment:

```powershell
kubectl get deploy serverless-llm -w
```

3. Confirm replicas reach 0.
4. Send new `/chat` request to wake service.
5. Confirm replicas scale up.

Acceptance checks:
- Replicas go to 0 during idle
- New traffic triggers scale-up

## Phase 6: Monitoring Stack in Kubernetes

Install kube-prometheus-stack:

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack -n monitoring --create-namespace -f .\monitoring\prometheus-values.yaml
```

Check pods:

```powershell
kubectl get pods -n monitoring
```

Open Grafana:

```powershell
minikube service monitoring-grafana -n monitoring --url
```

Import dashboard file:
- `monitoring/grafana-dashboard.json`

Acceptance checks:
- Request rate panel shows activity after `/chat` calls
- Latency panel shows p95 metric
- Replica panel reflects scale-up/down

## Phase 7: Jenkins Configuration (Critical)

Jenkins prerequisites:
- Jenkins agent can run Docker commands
- Jenkins has Python 3 installed
- Jenkins has kubectl and access to cluster

Create these credentials exactly:
1. `dockerhub-creds` -> Username/Password (or token)
2. `kubeconfig` -> Secret file (your kubeconfig)
3. `discord-webhook` -> Secret text (Discord webhook URL)

Pipeline setup:
1. New Pipeline job
2. Set **Definition** to `Pipeline script from SCM`
3. Set **SCM** to `Git` and use your repository URL
4. Set **Branch Specifier** to `*/main`
5. Set **Script Path** to `jenkins/Jenkinsfile` (exact case-sensitive path)
3. Trigger build

Acceptance checks:
- Test stage passes
- Image pushed with build number tag
- Deployment image updated in cluster
- Notify stage sends success message to Discord

## Phase 8: Failure Path Validation (AI DevOps Bot)

You must test failure flow once for demo credibility.

Method:
1. Introduce temporary failing test in `app/tests/test_smoke.py`.
2. Run Jenkins pipeline.
3. Confirm pipeline fails.
4. Confirm Discord receives failure embed with:
- Build URL
- Error summary
- Suggested fix

Then revert failing test and rerun pipeline.

Acceptance checks:
- Bot posts meaningful analysis generated by local Ollama
- On success rerun, green success embed is posted

## Phase 9: Portfolio-Ready Evidence Collection

Capture screenshots/logs for final submission:
- Jenkins pipeline success
- Jenkins pipeline failure + bot output
- Grafana dashboard with active metrics
- `kubectl get deploy` showing scale changes
- `/chat` API request + response

Also export these command outputs to a text file:

```powershell
kubectl get deploy,pods,svc,scaledobject -A > .\demo-evidence.txt
```

## What Is Left From My Side vs Your Side

From my side (code scaffold):
- Done for this phase
- No mandatory code files missing for requested architecture

From your side (environment/integration):
- Install and configure runtime tooling
- Run and validate local + k8s + Jenkins flows
- Provide real credentials in Jenkins
- Validate bot notifications and scale-to-zero behavior

## Recommended Final Hardening (Optional but Strong for Portfolio)

1. Add persistent volume claim for Ollama models in Kubernetes.
2. Add auth/rate limiting to `/chat` endpoint.
3. Add integration tests that mock Ollama responses.
4. Add SBOM and image scanning stage (Trivy/Grype) in Jenkins.
5. Add signed container images (cosign) and provenance.

## Common Pitfalls Checklist

- DockerHub repo name mismatch (`ullas911/serverless-llm` must match pipeline and manifests)
- Jenkins cannot access Docker daemon
- Kubeconfig credential points to wrong cluster
- Model pull not complete before first request
- Prometheus target not discovered due to service name mismatch
- Discord webhook blocked or malformed

## One-Command Daily Dev Start

After initial setup, daily local run:

```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d
```

Daily shutdown:

```powershell
docker compose down
```

## Completion Definition (Project Done)

Project is considered fully done when all are true:
- Local tests pass
- Local compose stack serves `/chat`
- Kubernetes deployment serves traffic
- KEDA scales to zero and back up
- Jenkins pipeline succeeds end-to-end
- Failure run triggers AI bot with useful fix suggestion
- Grafana dashboard shows real metrics during traffic
