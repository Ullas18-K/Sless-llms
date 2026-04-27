#!/usr/bin/env python3
"""
Purpose: Send Jenkins build status to Discord and ask Ollama to summarize failures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

FAILURE_PROMPT = (
    "You are a DevOps expert. Analyse this Jenkins build failure log. "
    "Identify the exact error, explain it in 2-3 sentences in plain English, "
    "and suggest the most likely fix in bullet points. Be concise."
)


def post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"HTTP {exc.code} {exc.reason} from {url!r} — Discord says: {error_body}"
        ) from exc


def analyze_failure_with_ollama(ollama_url: str, logs: str, model: str) -> str:
    prompt = f"{FAILURE_PROMPT}\n\nJenkins logs:\n{logs[:12000]}"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    response = post_json(f"{ollama_url.rstrip('/')}/api/generate", payload, timeout=90)
    return response.get("response", "No analysis returned by model.").strip()


def build_failure_embed(build_url: str, analysis: str, fallback_logs: str) -> dict[str, Any]:
    summary = analysis or "Analysis unavailable."
    suggested_fix = "See Jenkins logs and retry after applying the suggested corrections."

    if "-" in summary:
        parts = summary.split("\n")
        non_bullets = [line for line in parts if not line.strip().startswith("-")]
        bullets = [line for line in parts if line.strip().startswith("-")]
        if non_bullets:
            summary = "\n".join(non_bullets[:4]).strip()
        if bullets:
            suggested_fix = "\n".join(bullets[:6]).strip()

    if not analysis:
        suggested_fix = f"Raw log snippet:\n```\n{fallback_logs[:1000]}\n```"

    return {
        "title": "❌ Jenkins Build Failed — Analysis",
        "color": 16711680,
        "fields": [
            {"name": "Build URL", "value": build_url or "N/A", "inline": False},
            {"name": "Error Summary", "value": summary[:1024] or "N/A", "inline": False},
            {"name": "Suggested Fix", "value": suggested_fix[:1024] or "N/A", "inline": False},
        ],
    }


def build_success_embed(build_url: str, build_number: str) -> dict[str, Any]:
    return {
        "title": "✅ Jenkins Build Succeeded — Deployment Complete",
        "color": 65280,
        "fields": [
            {"name": "Build URL", "value": build_url or "N/A", "inline": False},
            {
                "name": "Status",
                "value": f"Build #{build_number or 'N/A'} passed tests, image push, and Kubernetes deployment.",
                "inline": False,
            },
        ],
    }


def send_discord(webhook_url: str, embed: dict[str, Any]) -> None:
    payload = {"embeds": [embed]}
    post_json(webhook_url, payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jenkins AI DevOps bot")
    parser.add_argument("--status", required=True, choices=["success", "failure"])
    parser.add_argument("--logs", default="")
    parser.add_argument("--build-url", default="")
    parser.add_argument("--webhook-url", required=True)
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--model", default=os.getenv("DEFAULT_MODEL", "tinyllama"))
    parser.add_argument("--build-number", default=os.getenv("BUILD_NUMBER", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.status == "success":
            embed = build_success_embed(args.build_url, args.build_number)
        else:
            analysis = ""
            try:
                analysis = analyze_failure_with_ollama(args.ollama_url, args.logs, args.model)
            except (urllib.error.URLError, TimeoutError, OSError):
                analysis = ""

            embed = build_failure_embed(args.build_url, analysis, args.logs)

        send_discord(args.webhook_url, embed)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"devops-bot failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
