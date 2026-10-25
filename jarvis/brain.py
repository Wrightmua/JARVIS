"""The thinking loop: send the conversation to the local model, run any tools it asks for (asking the
user first when a tool is risky), feed the results back, repeat until it answers in plain words."""
import asyncio
import json
import re
from typing import Awaitable, Callable

import ollama

from .config import MODEL, NUM_CTX, OLLAMA_HOST, USER_TITLE, WORKSPACE
from .store import store
from .tools import REGISTRY, clip, load

Emit = Callable[[dict], Awaitable[None]]
Confirm = Callable[[str], Awaitable[bool]]

MAX_TOOL_ROUNDS = 6
REMEMBER = re.compile(r"^(?:(?:hey |ok )?jarvis[,.!]?\s+)?(?:please\s+)?remember\s+(?:that\s+)?(.{3,})$", re.I)
HISTORY_MAX, HISTORY_KEEP = 16, 8  # trim rarely, so the model's prompt cache stays warm

PERSONA = f"""You are J.A.R.V.I.S., a personal AI assistant running locally on the user's Windows PC.
Personality: calm, precise, loyal, with dry British wit. Address the user as "{USER_TITLE}".

Your replies are SPOKEN ALOUD, so:
- Keep them short: one to three sentences unless asked for detail.
- Summarise tool results; give only the figures that matter, never recite everything.
- No markdown, bullet lists, emojis or URLs in speech.
- When you create code or long text, save it with write_file and just say what you made.

Use your tools whenever they help: control the PC, search the web, read pages, check weather and news,
manage files, and remember things. Never invent tool results; if a tool fails, say so briefly.
Live information (time, weather, system status, news, email, files) changes constantly: call the tool
again every time it is asked for, never repeat figures from earlier in the conversation.
For the current time or date, call get_time. When the user tells you something about themselves
worth keeping, call remember. Relative file paths go in the workspace: {WORKSPACE}"""


def system_prompt() -> str:
    facts = store.facts()
    if not facts:
        return PERSONA
    return PERSONA + "\n\nWhat you know about the user:\n" + "\n".join(f"- {t}" for _, t in facts)


def _text_tool_calls(text: str) -> list[tuple[str, dict]]:
    """Small models sometimes write a tool call as text instead of using the tool API."""
    blobs = re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.S)
    if not blobs and text.strip().startswith("{"):
        blobs = [text.strip()]
    calls = []
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        name = obj.get("name")
        args = obj.get("arguments", obj.get("parameters", {}))
        if name in REGISTRY:
            calls.append((name, args if isinstance(args, dict) else {}))
    return calls


def speakable(text: str) -> str:
    text = re.sub(r"```.*?```", " I've put the code on screen. ", text, flags=re.S)
    text = re.sub(r"https?://\S+", "the link", text)
    return re.sub(r"[*_#`>|]", "", text).strip()


class Brain:
    def __init__(self):
        load()
        self.client = ollama.AsyncClient(host=OLLAMA_HOST)
        self.history: list[dict] = []  # long-term memory is the facts table; small models parrot old replies
        self.tool_specs = [t.spec() for t in REGISTRY.values()]

    def reset(self):
        self.history = []

    async def status(self) -> dict:
        try:
            models = [m.model for m in (await self.client.list()).models]
        except Exception:
            return {"type": "status", "ready": False, "model": MODEL,
                    "detail": "Ollama isn't running. Start the Ollama app, then reload."}
        if not any(m == MODEL or m == f"{MODEL}:latest" for m in models):
            return {"type": "status", "ready": False, "model": MODEL,
                    "detail": f"Model not downloaded. Run: ollama pull {MODEL}"}
        return {"type": "status", "ready": True, "model": MODEL, "tools": sorted(REGISTRY)}

    async def warmup(self):
        try:
            await self.client.chat(model=MODEL, messages=[{"role": "system", "content": system_prompt()}],
                                   tools=self.tool_specs, options={"num_ctx": NUM_CTX, "num_predict": 1},
                                   keep_alive="2h")
        except Exception:
            pass

    async def _call_model(self, messages: list[dict], emit: Emit) -> tuple[str, list[tuple[str, dict]]]:
        content, calls, holding, started = "", [], False, False
        stream = await self.client.chat(model=MODEL, messages=messages, tools=self.tool_specs, stream=True,
                                        options={"num_ctx": NUM_CTX, "temperature": 0.4}, keep_alive="2h")
        async for chunk in stream:
            msg = chunk.message
            for tc in msg.tool_calls or []:
                calls.append((tc.function.name, dict(tc.function.arguments or {})))
            if msg.content:
                content += msg.content
                if not started and content.strip():
                    started = True
                    holding = content.lstrip()[0] in "{<"  # possibly a text tool call: don't show it
                    if not holding:
                        await emit({"type": "token", "text": content})
                elif started and not holding:
                    await emit({"type": "token", "text": msg.content})
        if not calls and holding:
            calls = _text_tool_calls(content)
            if calls:
                content = ""
            else:
                await emit({"type": "token", "text": content})
        return content, calls

    async def _run_tool(self, name: str, args: dict, emit: Emit, confirm: Confirm) -> str:
        tool = REGISTRY.get(name)
        if tool is None:
            return f"Unknown tool {name}. Available: {', '.join(REGISTRY)}"
        args = {k: v for k, v in args.items() if k in tool.params}
        await emit({"type": "tool", "name": name, "args": args})
        question = tool.confirmation(args)
        if question and not await confirm(question):
            return "The user declined. Do not retry; acknowledge briefly."
        try:
            result = await asyncio.to_thread(tool.fn, **args)
        except TypeError as e:
            result = f"Bad arguments for {name}: {e}"
        except Exception as e:  # tools touch the outside world; report failures to the model
            result = f"{name} failed: {type(e).__name__}: {e}"
        result = clip(str(result), 6000)
        await emit({"type": "tool_result", "name": name, "summary": result[:300]})
        return result

    async def respond(self, text: str, emit: Emit, confirm: Confirm) -> str:
        store.log("user", text)
        self.history.append({"role": "user", "content": text})
        if m := REMEMBER.match(text):  # small models sometimes claim to remember without saving
            fact = m.group(1).strip().rstrip(".")
            await emit({"type": "tool", "name": "remember", "args": {"fact": fact}})
            await emit({"type": "tool_result", "name": "remember", "summary": f"Saved fact #{store.add_fact(fact)}"})
            answer = f"Noted, {USER_TITLE}."
            await emit({"type": "token", "text": answer})
            self.history.append({"role": "assistant", "content": answer})
            store.log("assistant", answer)
            await emit({"type": "done", "text": answer, "speech": answer})
            return answer
        turn: list[dict] = []
        answer = ""
        system = system_prompt()  # fixed for the whole turn so the model's prompt cache stays valid
        for _ in range(MAX_TOOL_ROUNDS + 1):
            await emit({"type": "state", "value": "thinking"})
            messages = [{"role": "system", "content": system}, *self.history, *turn]
            content, calls = await self._call_model(messages, emit)
            if not calls:
                answer = content.strip()
                break
            turn.append({"role": "assistant", "content": content,
                         "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]})
            for name, args in calls:
                await emit({"type": "state", "value": "working"})
                turn.append({"role": "tool", "tool_name": name,
                             "content": await self._run_tool(name, args, emit, confirm)})
        else:
            answer = "I'm going round in circles on that one, I'm afraid. Could you rephrase?"
            await emit({"type": "token", "text": answer})

        answer = answer or "Done."
        self.history.append({"role": "assistant", "content": answer})
        if len(self.history) > HISTORY_MAX:
            self.history = self.history[-HISTORY_KEEP:]
        store.log("assistant", answer)
        await emit({"type": "done", "text": answer, "speech": speakable(answer)})
        return answer
