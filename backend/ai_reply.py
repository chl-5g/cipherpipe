#!/usr/bin/env python3
"""CipherPipe AI auto-reply bot — inbox monitor + LLM reply + idle timeout.
Set CP_AI_BACKEND in .env to choose: ollama | openai | anthropic."""
import asyncio, json, os, sys, time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

# Load .env
_env_path = os.path.join(PROJECT_DIR, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

INBOX = os.path.join(PROJECT_DIR, "data", "inbox.jsonl")
OUTBOX = os.path.join(PROJECT_DIR, "data", "outbox.jsonl")
IDLE_TIMEOUT = 30  # seconds

_SYSTEM = "你是 CipherPipe 的 AI 助手。简洁回复，不超过三句话。"

BACKEND = os.environ.get("CP_AI_BACKEND", "")


# ══════════════════════════════════════════
#  Ollama backend
# ══════════════════════════════════════════
async def _ollama_chat(text):
    url = os.environ.get("CP_AI_OLLAMA_URL", "")
    model = os.environ.get("CP_AI_OLLAMA_MODEL", "")
    if not url or not model:
        print("  [ollama] CP_AI_OLLAMA_URL and CP_AI_OLLAMA_MODEL required")
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 256},
    }

    def _post():
        import requests as req
        r = req.post(f"{url}/api/chat", json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()["message"]["content"].strip()
        return None

    try:
        return await asyncio.to_thread(_post)
    except Exception as e:
        print(f"  [ollama error] {e}")
        return None


# ══════════════════════════════════════════
#  OpenAI-compatible backend
# ══════════════════════════════════════════
async def _openai_chat(text):
    url = os.environ.get("CP_AI_OPENAI_URL", "")
    key = os.environ.get("CP_AI_OPENAI_KEY", "")
    model = os.environ.get("CP_AI_OPENAI_MODEL", "")
    if not url or not key or not model:
        print("  [openai] CP_AI_OPENAI_URL, CP_AI_OPENAI_KEY, CP_AI_OPENAI_MODEL required")
        return None

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": text},
        ],
        "max_tokens": 256,
        "temperature": 0.7,
    }

    def _post():
        import requests as req
        r = req.post(f"{url}/chat/completions", json=payload,
                     headers={"Authorization": f"Bearer {key}"}, timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return None

    try:
        return await asyncio.to_thread(_post)
    except Exception as e:
        print(f"  [openai error] {e}")
        return None


# ══════════════════════════════════════════
#  Anthropic-compatible backend
# ══════════════════════════════════════════
async def _anthropic_chat(text):
    url = os.environ.get("CP_AI_ANTHROPIC_URL", "")
    key = os.environ.get("CP_AI_ANTHROPIC_KEY", "")
    model = os.environ.get("CP_AI_ANTHROPIC_MODEL", "")
    if not url or not key or not model:
        print("  [anthropic] CP_AI_ANTHROPIC_URL, CP_AI_ANTHROPIC_KEY, CP_AI_ANTHROPIC_MODEL required")
        return None

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=key, base_url=url)
        resp = await client.messages.create(
            model=model,
            max_tokens=256,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        return resp.content[0].text
    except ImportError:
        print("  [anthropic] pip install anthropic")
        return None
    except Exception as e:
        print(f"  [anthropic error] {e}")
        return None


async def call_llm(message_text):
    backend = BACKEND
    if backend == "ollama":
        print("  [backend: ollama]")
        reply = await _ollama_chat(message_text)
    elif backend == "openai":
        print("  [backend: openai]")
        reply = await _openai_chat(message_text)
    elif backend == "anthropic":
        print("  [backend: anthropic]")
        reply = await _anthropic_chat(message_text)
    else:
        reply = None

    if reply:
        return reply
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
