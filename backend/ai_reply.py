#!/usr/bin/env python3
"""CipherPipe AI auto-reply bot — inbox monitor + LLM reply + idle timeout."""
import asyncio, json, os, sys, time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

INBOX = os.path.join(PROJECT_DIR, "data", "inbox.jsonl")
OUTBOX = os.path.join(PROJECT_DIR, "data", "outbox.jsonl")
IDLE_TIMEOUT = 30  # seconds

# ── LLM backend ──
_SYSTEM = "你是 CipherPipe 的 AI 助手。简洁回复，不超过三句话。"

async def call_llm(message_text):
    """Call Claude/GLM API. Falls back to echo if no key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GLM_API_KEY")
    if not api_key:
        return f"[echo] {message_text}"

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
        return f"[echo] {message_text}"
    except Exception as e:
        return f"[LLM error: {e}]"


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
