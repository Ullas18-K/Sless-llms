# Purpose: End-to-end setup guide for a serverless LLM DevOps + MLOps portfolio project.

# Serverless LLMs on Kubernetes with CI/CD, Autoscaling, and AI DevOps Bot

## 1) Project Overview

This project demonstrates a complete real-world DevOps + AI flow:
- FastAPI wraps an Ollama-hosted LLM for inference.
- Docker packages the API.
- Minikube + Kubernetes runs the app with an Ollama sidecar.
- KEDA scales the deployment down to zero when idle.
- Jenkins runs CI/CD: test -> build -> push -> deploy.
- Prometheus + Grafana monitor requests, latency, replicas, and build signals.
- AI DevOps Bot analyzes Jenkins failures with a local Ollama model and posts fixes to Discord.

## Architecture Diagram (ASCII)

```text
                   +----------------------------+
                   |        Developer            |
                   |  git push / manual trigger  |
                   +-------------+---------------+
                                 |
                                 v
+--------------------+   CI/CD   +--------------------------+
|      Jenkins       +-----------> Pipeline Stages          |
| (with credentials) |           | 1. Checkout              |
|                    |           | 2. Test (pytest)         |
|                    |           | 3. Build Docker image    |
|                    |           | 4. Push DockerHub        |
|                    |           | 5. Deploy to Minikube    |
+----+---------------+           | 6. Notify Discord        |
     |                           +-------------+------------+
     | failure logs                            |
     v                                         v
+------------------------+          +------------------------+
| Local Ollama (analysis)|          | Minikube Kubernetes    |
| via devops-bot.py      |          | Deployment:            |
+-----------+------------+          | - FastAPI container    |
            |                       | - Ollama sidecar       |
            v                       | - KEDA ScaledObject    |
+------------------------+          +------------+-----------+
| Discord Webhook        |                       |
| Plain-English RCA/Fix  |                       v
+------------------------+          +------------------------+
                                    | Prometheus + Grafana   |
                                    | Metrics + Dashboards   |
                                    +------------------------+
```

## 2) Prerequisites

Install these tools first:
- Docker Desktop
- Minikube
- kubectl
- Helm
- Jenkins (local or containerized)
- Python 3.11+
- DockerHub account
- Discord server with webhook permissions

## Create DockerHub Repo and Discord Webhook (Required)

### DockerHub
1. Sign in to DockerHub.
2. Create repository `serverless-llm` under your account.
3. Keep it public for easier demo pulls, or configure pull secrets for private use.
4. In Jenkins, add credentials ID `dockerhub-creds` as Username + Password/Token.

### Discord Webhook
1. In Discord: Server Settings -> Integrations -> Webhooks -> New Webhook.
2. Select a channel and copy the webhook URL.
3. In Jenkins, add Secret Text credential ID `discord-webhook` using that URL.
4. Do not commit this URL in source code.

## 3) Local Setup (Docker Compose Dev Mode)

From project root:

```bash
docker compose up -d --build
```

Pull the model into local Ollama container:

```bash
docker exec -it ollama ollama pull tinyllama
```

Test API:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Say hello from TinyLlama","model":"tinyllama"}'
```

Open tools:
- API docs: http://localhost:8000/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

## 4) Kubernetes Deployment (Minikube)

Start cluster and install KEDA:

```bash
minikube start
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace
```

Optional (HTTP trigger path):

```bash
helm install keda-http-add-on kedacore/keda-add-ons-http --namespace keda
```

Deploy app manifests:

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/ingress.yaml
kubectl get pods -w
```

Demo access via NodePort:

```bash
minikube service serverless-llm-nodeport --url
```

## 5) Jenkins Setup

1. Create a Pipeline job and point it to this repository.
2. Ensure Jenkins agent has Docker, Python 3, kubectl access.
3. Add credentials:
- `dockerhub-creds` (Username + Password/Token)
- `kubeconfig` (Secret file)
- `discord-webhook` (Secret text)
4. Run the pipeline defined in `jenkins/Jenkinsfile`.

Pipeline stages:
- Checkout
- Test
- Build
- Push
- Deploy
- Notify

On failure, Jenkins sends logs to `jenkins/devops-bot.py`, which asks Ollama for analysis and posts Discord guidance.

## 6) Trigger AI DevOps Bot Manually

```bash
python jenkins/devops-bot.py \
  --status failure \
  --logs "ModuleNotFoundError: No module named fastapi" \
  --build-url "http://localhost:8080/job/serverless-llm/1/" \
  --webhook-url "<your-discord-webhook>" \
  --ollama-url "http://localhost:11434"
```

Success notification test:

```bash
python jenkins/devops-bot.py \
  --status success \
  --build-url "http://localhost:8080/job/serverless-llm/2/" \
  --build-number "2" \
  --webhook-url "<your-discord-webhook>" \
  --ollama-url "http://localhost:11434"
```

## 7) Monitoring Setup (Prometheus + Grafana)

Install kube-prometheus-stack:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f monitoring/prometheus-values.yaml
```

Access Grafana:

```bash
minikube service monitoring-grafana -n monitoring --url
```

Import dashboard JSON from:
- `monitoring/grafana-dashboard.json`

## 8) How KEDA Scale-to-Zero Works Here

The ScaledObject in `k8s/hpa.yaml` watches Prometheus query:
- `sum(rate(http_requests_total{path="/chat"}[1m]))`

Behavior:
- No traffic -> replicas drop to 0 after cooldown period.
- New traffic -> KEDA scales deployment up (up to max replicas).

Quick test:

```bash
kubectl get deploy serverless-llm -w
# wait for replicas 0 (idle)
curl -X POST "$(minikube service serverless-llm-nodeport --url)/chat" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"wake up","model":"tinyllama"}'
```

## 9) Troubleshooting

### Ollama slow startup
- First model pull can be several minutes.
- Check sidecar logs: `kubectl logs deploy/serverless-llm -c ollama`
- Consider pre-pulling model on node for demos.

### KEDA not scaling
- Verify KEDA operator: `kubectl get pods -n keda`
- Verify Prometheus query returns values.
- Confirm `http_requests_total` includes `/chat` label values.

### Jenkins Docker socket issues
- If Jenkins cannot run Docker, mount Docker socket or use DinD.
- Verify Jenkins user permissions for Docker daemon.
- Confirm `docker login` works with `dockerhub-creds`.

### Discord notification missing
- Validate `discord-webhook` credential value.
- Run manual script test in Jenkins agent shell.
- Confirm Jenkins can reach webhook endpoint.

## 10) Important Project Customization

Update these values for your environment:
- Docker image repo in `jenkins/Jenkinsfile` and `k8s/deployment.yaml` (already set to `ullas911/serverless-llm`).
- If using another model (like `phi3:mini`), update:
  - `DEFAULT_MODEL` env vars
  - initContainer `ollama pull` command
  - test payload model name
