#!/usr/bin/env python3
"""Quick LLM connectivity and response-speed benchmark.

Examples:
  python tools/bench_llm_speed.py --provider ollama --model qwen2.5vl
  python tools/bench_llm_speed.py --provider openai --base-url http://127.0.0.1:11434/v1 --model llama3.2-vision
  python tools/bench_llm_speed.py --provider openai --env backend/.env --model glm-5-outside
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: str | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path:
        return values
    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(f"env file not found: {env_path}")
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def request_json(
    url: str,
    payload: dict,
    headers: dict[str, str],
    timeout: int,
    verify_ssl: bool,
):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    context = None if verify_ssl else ssl._create_unverified_context()
    return urllib.request.urlopen(req, timeout=timeout, context=context)


def iter_ollama_stream(resp):
    for line in resp:
        if not line.strip():
            continue
        data = json.loads(line.decode("utf-8"))
        if data.get("message", {}).get("content"):
            yield data["message"]["content"]


def iter_openai_sse(resp):
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="ignore").strip()
        if not line.startswith("data: "):
            continue
        body = line[6:]
        if body == "[DONE]":
            break
        data = json.loads(body)
        choices = data.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        text = delta.get("content")
        if text:
            yield text


def bench_stream(name: str, resp, chunk_iter, request_start: float):
    stream_start = time.perf_counter()
    first_at: float | None = None
    text_parts: list[str] = []

    for text in chunk_iter(resp):
        if first_at is None:
            first_at = time.perf_counter()
        text_parts.append(text)

    end = time.perf_counter()
    full_text = "".join(text_parts)
    stream_total = end - stream_start
    end_to_end_total = end - request_start
    first = None if first_at is None else first_at - request_start
    header = stream_start - request_start
    speed = (len(full_text) / end_to_end_total) if end_to_end_total > 0 else 0

    print(f"provider={name}")
    print(f"ok=true")
    print(f"total_seconds={end_to_end_total:.3f}")
    print(f"headers_seconds={header:.3f}")
    print(f"stream_seconds={stream_total:.3f}")
    print(f"first_chunk_seconds={first:.3f}" if first is not None else "first_chunk_seconds=<none>")
    print(f"chars={len(full_text)}")
    print(f"chars_per_second={speed:.1f}")
    print("preview=" + full_text[:500].replace("\n", "\\n"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", default="你好，请用三句话介绍一下你自己。")
    parser.add_argument("--env", default="")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    env = load_env(args.env)

    if args.provider == "ollama":
        base_url = (args.base_url or env.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        model = args.model or env.get("OLLAMA_MODEL") or env.get("OLLAMA_VISION_MODEL")
        if not model:
            print("ERROR: missing model. Pass --model or set OLLAMA_MODEL/OLLAMA_VISION_MODEL.", file=sys.stderr)
            return 2
        url = f"{base_url}/api/chat"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": args.prompt}],
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        verify_ssl = True
        stream_iter = iter_ollama_stream
    else:
        base_url = (args.base_url or env.get("AIRCHINA_BASE_URL") or env.get("OPENAI_BASE_URL") or "http://127.0.0.1:11434/v1").rstrip("/")
        model = args.model or env.get("MODEL_CHAT") or env.get("OPENAI_MODEL")
        api_key = env.get("AIRCHINA_API_KEY") or env.get("OPENAI_API_KEY") or "ollama"
        if not model:
            print("ERROR: missing model. Pass --model or set MODEL_CHAT/OPENAI_MODEL.", file=sys.stderr)
            return 2
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": args.prompt}],
            "temperature": 0.6,
            "max_tokens": 300,
            "stream": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        host_header = env.get("AI_HTTP_HOST_HEADER", "")
        if host_header:
            headers["Host"] = host_header
        verify_ssl = env.get("AI_HTTP_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no", "off"}
        stream_iter = iter_openai_sse

    print(f"url={url}")
    print(f"model={model}")
    print(f"prompt={args.prompt}")
    print(f"verify_ssl={verify_ssl}")
    if "Host" in headers:
        print(f"host_header={headers['Host']}")

    try:
        request_start = time.perf_counter()
        with request_json(url, payload, headers, args.timeout, verify_ssl) as resp:
            print(f"http_status={resp.status}")
            bench_stream(args.provider, resp, stream_iter, request_start)
    except urllib.error.HTTPError as e:
        print(f"ok=false")
        print(f"http_status={e.code}")
        print(e.read().decode("utf-8", errors="ignore")[:1000])
        return 1
    except Exception as e:
        print("ok=false")
        print(f"error={type(e).__name__}: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
