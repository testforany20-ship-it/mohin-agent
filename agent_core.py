#!/usr/bin/env python3
"""Agent core for the WEB version of MOHIN's personal AI agent.

Ported faithfully from ~/workspace/ai-agent/agent.py (Telegram version, v1,
2026-11-10): same Gemini agent loop (function calling, max ~6 tool rounds),
same tools, same model fallback list, same SOUL.md + MEMORY.md system prompt.

Differences from the Telegram version:
- No Telegram polling / owner pairing (the web app gates access with a
  password instead — see streamlit_app.py).
- State files (memory.json, MEMORY.md, reminders.json) live in a data dir
  given at construction (the web app uses <app dir>/data/). Reminders have no
  chat to push to: they are stored and the web app surfaces due ones on the
  next visit.
- Publishing is deliberately NOT a tool (same as agent.py).

Stdlib only (urllib), like the original.
"""
import json
import os
import re
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOUL_PATH = os.path.join(BASE_DIR, "SOUL.md")

TZ = ZoneInfo("Asia/Dhaka")
MAX_TOOL_ROUNDS = 6

GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-lite-latest"]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

BLOG_FEED_JSON = (
    "https://mohintechbd.blogspot.com/feeds/posts/default?alt=json&max-results=5"
)


# ---------------------------------------------------------------------------
# Small file helpers (same style as agent.py)
# ---------------------------------------------------------------------------

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def http_json(url, payload=None, headers=None, timeout=60):
    data = None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ai-agent-web)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

class WebAgent:
    def __init__(self, gemini_key, data_dir):
        self.gemini_key = gemini_key
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.memory_json_path = os.path.join(data_dir, "memory.json")
        self.memory_md_path = os.path.join(data_dir, "MEMORY.md")
        self.reminders_path = os.path.join(data_dir, "reminders.json")
        self.system_prompt = self.build_system_prompt()

    def build_system_prompt(self):
        soul = ""
        if os.path.exists(SOUL_PATH):
            with open(SOUL_PATH, "r", encoding="utf-8") as f:
                soul = f.read().strip()
        memory_md = ""
        if os.path.exists(self.memory_md_path):
            with open(self.memory_md_path, "r", encoding="utf-8") as f:
                memory_md = f.read().strip()
        parts = [soul]
        if memory_md:
            parts.append(
                "\n\n## What you remember about MOHIN (from MEMORY.md)\n" + memory_md[-8000:]
            )
        return "\n".join(parts)

    # ---------- Tools ----------
    def tool_get_current_time(self):
        now = datetime.now(TZ)
        return (
            f"Current time in Bangladesh (Asia/Dhaka): "
            f"{now.strftime('%A, %d %B %Y, %I:%M %p')} "
            f"({now.strftime('%Y-%m-%d %H:%M')})"
        )

    def tool_remember(self, key, value):
        key = (key or "").strip()
        value = (value or "").strip()
        if not key or not value:
            return "remember failed: both key and value are required."
        mem = load_json(self.memory_json_path, {})
        mem[key] = value
        save_json(self.memory_json_path, mem)
        stamp = datetime.now(TZ).strftime("%Y-%m-%d")
        with open(self.memory_md_path, "a", encoding="utf-8") as f:
            f.write(f"- ({stamp}) **{key}**: {value}\n")
        return f"Saved to memory: {key} = {value}"

    def tool_recall(self, query):
        query = (query or "").strip()
        mem = load_json(self.memory_json_path, {})
        if not mem:
            return "Memory is empty — nothing has been saved yet."
        if not query:
            return json.dumps(mem, ensure_ascii=False)
        q = query.lower()
        words = [w for w in re.split(r"\W+", q) if len(w) > 1]
        hits = {}
        for k, v in mem.items():
            hay = (k + " " + str(v)).lower()
            if q in hay or any(w in hay for w in words):
                hits[k] = v
        if not hits:
            return (
                "No memory entry matches that query. Full memory keys: "
                + ", ".join(mem.keys())
            )
        return json.dumps(hits, ensure_ascii=False)

    def tool_latest_blog_posts(self):
        try:
            data = http_json(BLOG_FEED_JSON, timeout=30)
        except Exception as e:
            return f"Could not fetch the blog feed: {e!r}"
        entries = data.get("feed", {}).get("entry", [])
        if not entries:
            return "The blog feed returned no posts."
        lines = ["Latest posts on MOHIN TECH (mohintechbd.blogspot.com):"]
        for e in entries[:5]:
            title = e.get("title", {}).get("$t", "(no title)")
            link = ""
            for l in e.get("link", []):
                if l.get("rel") == "alternate":
                    link = l.get("href", "")
                    break
            published = e.get("published", {}).get("$t", "")[:16].replace("T", " ")
            lines.append(f"- {title}\n  {link}\n  published: {published}")
        return "\n".join(lines)

    def tool_fetch_url_text(self, url):
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return "fetch_url_text failed: URL must start with http:// or https://"
        try:
            html = http_text(url, timeout=30)
        except Exception as e:
            return f"Could not fetch {url}: {e!r}"
        html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"&(nbsp|amp|lt|gt|quot|#39);", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return (f"Text from {url} (truncated to 4000 chars):\n" + text[:4000])

    def tool_set_reminder(self, text, minutes_from_now):
        text = (text or "").strip()
        try:
            minutes = float(minutes_from_now)
        except (TypeError, ValueError):
            return "set_reminder failed: minutes_from_now must be a number."
        if not text or minutes <= 0:
            return "set_reminder failed: need reminder text and minutes > 0."
        due = datetime.now(TZ) + timedelta(minutes=minutes)
        rems = load_json(self.reminders_path, [])
        rems.append({
            "text": text,
            "due_epoch": due.timestamp(),
            "due_human": due.strftime("%Y-%m-%d %H:%M Asia/Dhaka"),
            "shown": False,
        })
        save_json(self.reminders_path, rems)
        return (
            f"Reminder set for {due.strftime('%d %B %Y, %I:%M %p')} "
            f"(Bangladesh time): {text}. Note: on this website the reminder "
            f"will be shown to MOHIN at the top of the page the next time he "
            f"visits after it comes due — it cannot push a notification."
        )

    def due_reminders(self):
        """Return due, not-yet-shown reminders (does not modify the file)."""
        import time as _time
        now = _time.time()
        rems = load_json(self.reminders_path, [])
        return [r for r in rems
                if r.get("due_epoch", 0) <= now and not r.get("shown")]

    def mark_reminders_shown(self, shown_list):
        """Mark the given reminder dicts as shown so they surface only once."""
        rems = load_json(self.reminders_path, [])
        keys = {(r.get("due_epoch"), r.get("text")) for r in shown_list}
        for r in rems:
            if (r.get("due_epoch"), r.get("text")) in keys:
                r["shown"] = True
        save_json(self.reminders_path, rems)

    # ---------- Gemini ----------
    def _gemini_call(self, payload):
        """Try the model fallback list; return the parsed response."""
        last_err = None
        for model in GEMINI_MODELS:
            try:
                return http_json(
                    GEMINI_URL.format(model),
                    payload,
                    headers={"x-goog-api-key": self.gemini_key},
                    timeout=120,
                )
            except Exception as e:
                last_err = e
                print("Gemini model failed:", model, repr(e)[:200], flush=True)
                continue
        raise last_err if last_err else RuntimeError("Gemini unreachable")

    def _draft_article(self, topic):
        """Plain (tool-less) Gemini call used by the draft_article tool."""
        prompt = (
            "Write an original English news/blog article draft on this topic for "
            "MOHIN TECH (US-audience English news blog):\n\n"
            f"Topic: {topic}\n\n"
            "Rules: 500-800 words, straight news tone, 2-4 subheads, a title on the "
            "first line. NEVER invent facts, quotes, numbers or names — if key facts "
            "are unknown, write around them and add a short 'TO CHECK:' note at the "
            "end listing what must be verified before publishing. This is a draft "
            "only; it will not be published as-is."
        )
        payload = {
            "system_instruction": {"parts": [{"text": self.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        }
        res = self._gemini_call(payload)
        cands = res.get("candidates") or []
        if not cands:
            return "draft_article failed: Gemini returned no candidates."
        parts = cands[0].get("content", {}).get("parts", [])
        out = "".join(p.get("text", "") for p in parts).strip()
        return out or "draft_article failed: empty response from Gemini."

    def _run_tool(self, name, args):
        args = args or {}
        try:
            if name == "get_current_time":
                return self.tool_get_current_time()
            if name == "remember":
                return self.tool_remember(args.get("key", ""), args.get("value", ""))
            if name == "recall":
                return self.tool_recall(args.get("query", ""))
            if name == "latest_blog_posts":
                return self.tool_latest_blog_posts()
            if name == "fetch_url_text":
                return self.tool_fetch_url_text(args.get("url", ""))
            if name == "draft_article":
                return self._draft_article(args.get("topic", ""))
            if name == "set_reminder":
                return self.tool_set_reminder(args.get("text", ""),
                                              args.get("minutes_from_now"))
            return f"Unknown tool: {name}"
        except Exception as e:
            traceback.print_exc()
            return f"Tool {name} raised an error: {e!r}"

    def agent_loop(self, history, user_text):
        """Run the agent loop for one user message; return the final text reply.

        history: list of [role, text] pairs ("user"/"model") from earlier turns.
        """
        contents = []
        for role, text in history[-12:]:
            contents.append(
                {"role": "user" if role == "user" else "model",
                 "parts": [{"text": text}]}
            )
        contents.append({"role": "user", "parts": [{"text": user_text}]})

        for _round in range(MAX_TOOL_ROUNDS + 1):
            payload = {
                "system_instruction": {"parts": [{"text": self.system_prompt}]},
                "contents": contents,
                "tools": [{"function_declarations": TOOL_DECLARATIONS}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
            }
            res = self._gemini_call(payload)
            cands = res.get("candidates") or []
            if not cands:
                return "দুঃখিত, AI থেকে কোনো উত্তর আসেনি। আবার চেষ্টা করো।"
            content = cands[0].get("content", {})
            parts = content.get("parts", [])
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                out = "".join(p.get("text", "") for p in parts).strip()
                return out or "দুঃখিত, খালি উত্তর এসেছে। আবার চেষ্টা করো।"
            # Feed the model's tool calls and our results back in, then loop.
            contents.append({"role": "model", "parts": parts})
            response_parts = []
            for call in calls:
                result = self._run_tool(call.get("name", ""), call.get("args") or {})
                response_parts.append({
                    "functionResponse": {
                        "name": call.get("name", ""),
                        "response": {"result": result},
                    }
                })
            contents.append({"role": "user", "parts": response_parts})
        return "দুঃখিত, অনেকগুলো ধাপ হয়ে গেছে — কাজটা ভেঙে ছোট করে আবার বলো।"


TOOL_DECLARATIONS = [
    {
        "name": "get_current_time",
        "description": "Get the current date and time in Bangladesh (Asia/Dhaka). "
                       "Use whenever MOHIN asks what time/day it is.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "remember",
        "description": "Save a fact about MOHIN persistently (survives restarts). "
                       "Use whenever he tells you something worth keeping: "
                       "preferences, names, decisions, deadlines, rules.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING",
                        "description": "Short label for the fact, e.g. 'favourite_colour'"},
                "value": {"type": "STRING",
                          "description": "The fact itself, in the language MOHIN used"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall",
        "description": "Search persistent memory for facts about MOHIN. Use before "
                       "answering questions about him, his preferences or his work.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING",
                          "description": "What to look for; empty string returns all memory"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "latest_blog_posts",
        "description": "Fetch the 5 latest posts on MOHIN TECH "
                       "(mohintechbd.blogspot.com) with titles, links and times.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "fetch_url_text",
        "description": "Fetch a web page and return its readable text "
                       "(truncated to ~4000 chars). Use to read links MOHIN sends.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Full http(s) URL"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "draft_article",
        "description": "Draft an English news/blog article on a topic (500-800 words, "
                       "subheads). DRAFT ONLY — never publishes anything.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic": {"type": "STRING", "description": "The article topic/headline"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "set_reminder",
        "description": "Set a reminder: it will be shown to MOHIN at the top of "
                       "this web page the next time he visits after it comes due.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "What to remind about"},
                "minutes_from_now": {"type": "NUMBER",
                                     "description": "Minutes from now until the reminder"},
            },
            "required": ["text", "minutes_from_now"],
        },
    },
]
