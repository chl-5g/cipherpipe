#!/usr/bin/env python3
"""CipherPipe AI auto-reply bot — inbox monitor + LLM reply + idle timeout.
LLM backend: local Ollama → remote API → echo fallback."""
import asyncio, json, os, sys, time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

INBOX = os.path.join(PROJECT_DIR, "data", "inbox.jsonl")
OUTBOX = os.path.join(PROJECT_DIR, "data", "outbox.jsonl")
IDLE_TIMEOUT = 30  # seconds

_SYSTEM = "你是 CipherPipe 的 AI 助手。简洁回复，不超过三句话。"

# ── Local LLM config ──
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b-nothink")


def _check_ollama_sync():
    """Return True if Ollama is reachable."""
    try:
        import requests as req
        r = req.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


async def _check_ollama():
    return await asyncio.to_thread(_check_ollama_sync)


def _call_ollama_sync(message_text):
    """Call local Ollama model (sync)."""
    import requests as req
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": message_text},
        ],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 256},
    }
    r = req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60)
    if r.status_code == 200:
        return r.json()["message"]["content"].strip()
    return None


async def call_ollama(message_text):
    try:
        return await asyncio.to_thread(_call_ollama_sync, message_text)
    except Exception as e:
        print(f"  [ollama error] {e}")
        return None


async def call_remote_api(message_text):
    """Call remote LLM via Anthropic-compatible API."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GLM_API_KEY")
    if not api_key:
        return None
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    model = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
        resp = await client.messages.create(
            model=model,
            max_tokens=256,
            system=_SYSTEM,
            messages=[{"role": "user", "content": message_text}],
        )
        return resp.content[0].text
    except ImportError:
        return None
    except Exception as e:
        print(f"  [api error] {e}")
        return None


async def call_llm(message_text):
    """Try local Ollama first, then remote API, then echo."""
    # 1. Local Ollama
    if await _check_ollama():
        print("  [backend: ollama]")
        reply = await call_ollama(message_text)
        if reply:
            return reply

    # 2. Remote API
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GLM_API_KEY")
    if api_key:
        print("  [backend: remote api]")
        reply = await call_remote_api(message_text)
        if reply is not None:
            return reply

    # 3. Echo fallback
    return f"[echo] {message_text}"


async def main():
    # Start from end of existing inbox
    try:
        with open(INBOX, "r") as f:
            f.seek(0, 2)  # seek to end
            last_pos = f.tell()
    except FileNotFoundError:
        last_pos = 0

    last_activity = time.time()

    while True:
        try:
            with open(INBOX, "r") as f:
                f.seek(last_pos)
                new_lines = f.readlines()
                last_pos = f.tell()
        except FileNotFoundError:
            await asyncio.sleep(1)
            continue

        if new_lines:
            last_activity = time.time()
            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("from") == "me":
                    continue
                text = msg.get("text", "")
                sender = msg.get("from", "")
                print(f"[收到] {sender[:12]}: {text[:100]}")
                reply = await call_llm(text)
                if reply:
                    with open(OUTBOX, "a") as f:
                        f.write(reply + "\n")
                    print(f"[回复] {reply[:100]}")

        if time.time() - last_activity > IDLE_TIMEOUT:
            print("[超时] 30秒无新消息，退出")
            break

        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
