#!/usr/bin/env python3
"""MOHIN's AI Agent — private web chat (Streamlit).

The web version of MOHIN's personal AI agent (the Telegram version lives in
~/workspace/ai-agent/agent.py). Same agent core (agent_core.py), same SOUL.md
rules, same tools — behind a password gate, because this site is for MOHIN
only.

Access gate:
- App data lives in ./data/. data/auth.json stores ONLY a salted SHA-256 hash
  of the password.
- No hash yet → "Claim this app" screen: enter the one-time SETUP_CODE
  (from Streamlit secrets); on a match, create your own password. The setup
  code stops working as soon as a password exists.
- Hash exists → password login. Correct password → chat.

Secrets required (Streamlit Cloud → app settings → Secrets):
  GEMINI_API_KEY = "..."
  SETUP_CODE = "..."
"""
import hashlib
import hmac
import os
import secrets as _secrets

import streamlit as st

from agent_core import WebAgent, load_json, save_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
AUTH_PATH = os.path.join(DATA_DIR, "auth.json")

st.set_page_config(page_title="MOHIN's AI Agent", page_icon="🤖")


# ---------------------------------------------------------------------------
# Secrets / auth helpers
# ---------------------------------------------------------------------------

def get_secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""


def load_auth():
    if os.path.exists(AUTH_PATH):
        try:
            data = load_json(AUTH_PATH, None)
            if data and data.get("salt") and data.get("hash"):
                return data
        except Exception:
            pass
    return None


def hash_password(salt, password):
    return hashlib.sha256((salt + "\x00" + password).encode("utf-8")).hexdigest()


def save_password(password):
    os.makedirs(DATA_DIR, exist_ok=True)
    salt = _secrets.token_hex(16)
    save_json(AUTH_PATH, {"salt": salt, "hash": hash_password(salt, password)})


def check_password(password, auth):
    return hmac.compare_digest(hash_password(auth["salt"], password), auth["hash"])


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

def claim_screen():
    st.title("🤖 MOHIN's AI Agent")
    st.subheader("Claim this app")
    st.write(
        "This private agent has not been claimed yet. Enter the one-time "
        "setup code, then choose your own password. After this step the "
        "setup code stops working and only your password opens the app."
    )
    with st.form("claim_form"):
        code = st.text_input("Setup code", type="password")
        pw1 = st.text_input("New password", type="password")
        pw2 = st.text_input("New password again", type="password")
        submitted = st.form_submit_button("Claim this app")
    if submitted:
        expected = get_secret("SETUP_CODE")
        if not expected:
            st.error("Server is missing the SETUP_CODE secret — the app "
                     "owner must set it in Streamlit secrets first.")
        elif not hmac.compare_digest(code.strip(), expected.strip()):
            st.error("Setup code does not match. Nothing was changed.")
        elif len(pw1) < 6:
            st.error("Password is too short — use at least 6 characters.")
        elif pw1 != pw2:
            st.error("The two passwords do not match. Try again.")
        else:
            save_password(pw1)
            st.session_state["authed"] = True
            st.success("Done — this app is yours now. Opening your agent…")
            st.rerun()


def login_screen():
    st.title("🤖 MOHIN's AI Agent")
    st.subheader("Private — owner's password needed")
    with st.form("login_form"):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        auth = load_auth()
        if auth and check_password(pw, auth):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")


def get_agent():
    agent = st.session_state.get("agent")
    if agent is None:
        key = get_secret("GEMINI_API_KEY")
        if not key:
            st.error("Server is missing the GEMINI_API_KEY secret — the app "
                     "owner must set it in Streamlit secrets first.")
            st.stop()
        agent = WebAgent(key, DATA_DIR)
        st.session_state["agent"] = agent
    return agent


def chat_screen():
    st.title("🤖 MOHIN's AI Agent")
    agent = get_agent()

    # Due reminders surface once, at the top, on the next visit after due.
    if not st.session_state.get("reminders_shown"):
        due = agent.due_reminders()
        if due:
            for r in due:
                st.warning(f"⏰ **Reminder:** {r.get('text', '')} "
                           f"(was due {r.get('due_human', '')})")
            agent.mark_reminders_shown(due)
        st.session_state["reminders_shown"] = True

    if "history" not in st.session_state:
        st.session_state["history"] = []          # [[role, text], ...] for the core
        st.session_state["messages"] = []         # chat display history

    if not st.session_state["messages"]:
        st.chat_message("assistant").write(
            "আসসালামু আলাইকুম MOHIN! আমি তোমার নিজের AI এজেন্ট (ওয়েব সংস্করণ)।\n\n"
            "আমি যা করতে পারি:\n"
            "• তুমি যা বলবে মনে রাখি — পরে জিজ্ঞেস করলেই বলে দিই\n"
            "• এখনকার সময়, MOHIN TECH-এর সর্বশেষ পোস্ট দেখে দিই\n"
            "• যেকোনো ওয়েব পেজ পড়ে সারাংশ দিই\n"
            "• Topic দিলে English article-এর draft লিখে দিই (publish করি না)\n"
            "• Reminder সেট করি — সময় পার হলে পরের visit-এ উপরে দেখিয়ে দিই\n\n"
            "শুধু বলো কী করতে হবে।"
        )

    for m in st.session_state["messages"]:
        st.chat_message(m["role"]).write(m["content"])

    prompt = st.chat_input("এখানে লেখো… / Type here…")
    if prompt:
        st.session_state["messages"].append(
            {"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        with st.chat_message("assistant"):
            with st.spinner("ভাবছি…"):
                try:
                    reply = agent.agent_loop(st.session_state["history"], prompt)
                except Exception:
                    reply = ("AI সার্ভিসে সমস্যা হচ্ছে (Gemini)। "
                             "একটু পরে আবার পাঠাও।")
            st.write(reply)
        st.session_state["messages"].append(
            {"role": "assistant", "content": reply})
        history = st.session_state["history"]
        history.append(["user", prompt])
        history.append(["model", reply])
        st.session_state["history"] = history[-24:]
        # Memory may have grown during this turn; refresh the system prompt.
        agent.system_prompt = agent.build_system_prompt()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    auth = load_auth()
    if not st.session_state.get("authed"):
        if auth is None:
            claim_screen()
        else:
            login_screen()
        return
    chat_screen()


main()
