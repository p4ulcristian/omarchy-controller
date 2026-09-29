"""Compose (Create): tell Claude what to write, and watch the box.
Hold Create and say what you want ("write that I'll be late, keep it short",
"put my site in, kakapo dot com, spelled K A K A P O"). The model (Claude
Haiku through the Claude Code CLI, or a local Ollama model) writes the text,
and the focused box changes to it right away. Keep talking to change it ("shorter", "drop the last sentence").
Compose.qml next to this file shows your last prompt on top and the draft
under it, and the last texts you finished. ✕ = done, △ = undo the last change,
○ = put the box back; D-pad ←/→ and □ put a recent text into the draft.

The box is changed in place: only the end that differs is erased
(Backspace) and the new end pasted, so it works in terminals too and never
touches text that was there before. L2 + Create instead starts from the
box's whole text (select all, copy), and each change replaces all of it.

Needs the dictate socket to take "stop-return" (see modes/talk.py)."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.request

from evdev import ecodes as e

from ...core.config import CONFIG
from ...device import profiles
from ...keymap.bindings import CTRL, SUPER
from ...modes.talk import DICTATE_SOCK, dictate, stop_return

log = logging.getLogger("iris-controller")

PLUGIN = "p4ulcristian.iris-controller-compose"
_cfg = CONFIG.get("compose", {})
# "claude": the Claude Code CLI (your subscription's login, no API key), model
# haiku by default. "ollama": a local model (gemma4:e4b by default).
BACKEND = _cfg.get("backend", "claude")
MODEL = _cfg.get("model", "haiku" if BACKEND == "claude" else "gemma4:e4b")
OLLAMA = _cfg.get("url", "http://127.0.0.1:11434").rstrip("/")
CLAUDE = os.path.expanduser(_cfg.get("claude", "")) or shutil.which("claude") or "claude"
# Texts finished with ✕, newest first: the panel offers them again (D-pad, □).
RECENT_FILE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
                           "iris-controller", "compose-recent.json")
RECENT_KEPT = 8
ENABLED = bool(DICTATE_SOCK) and _cfg.get("enabled", True)
CLIP_WAIT = 0.15      # after a copy / before a paste: let the clipboard settle
BACKSPACES_PER_TICK = 40

SYSTEM = """What this is: a voice text box. The user sits at their computer without a keyboard (they use a gamepad) and fills a real input box by talking: a chat message, a search, a URL, an email address, a prompt to an AI assistant. Your job is to make the box say exactly what they want, and to keep fixing it as they talk, until it's right.

How their words reach you: a speech recognizer turns their voice into the "Said" line. Nobody checks it. It makes typical machine mistakes:
- sound-alike words ("write" / "right", "Otto" / "auto"),
- words split or merged ("batwit Oto" is "but with Otto", "kaka po" is "kakapo"),
- names and brands turned into ordinary words ("sales force" can be the brand "Salesforce").
So read the "Said" line by how it sounds, not only by what it literally says, and use the current text and the conversation to decide what they meant.

You are the user's hands on the keyboard.

Every turn you get the box's current text and what they just said to you. What they say is them talking TO YOU about the text:
- An instruction ("say I'm late", "shorter", "add sorry at the start", "make it a list"): do it.
- A correction of your last change ("no", "I meant", "not like that", "at the start", "one word"): your last change was wrong. Throw it away completely and do what they meant. Their correction never goes into the text.
- Words to put in, when they are plainly dictating content: put them in, cleaned up.
Their instructions, corrections and comments are never text for the box.

Speech gets misheard, so work out what they mean from the whole conversation, not the literal words:
- A word spelled letter by letter is spelled exactly that way.
- A word described in parts ("the word sunshine but with Moon at the start") is that new word, written as one word: Moonshine.
- Spoken "dot" in a domain is ".", "at" in an email is "@".
- "The previous one", "go back" mean an earlier version from this conversation: output it again.
- A short phrase that only makes sense about the current text ("but with …", "with a P", "at the start", "one word") changes the current text; it never replaces it.
Keep everything they didn't ask to change exactly as it is. Write in their voice, as the text itself.

Output only the box's whole new text. Never answer them, never explain, no quotes.

Examples:
Text: (empty)
Said: say I'll be about ten minutes late
New text: I'll be about 10 minutes late.

Text: I'll be about 10 minutes late.
Said: add sorry at the start
New text: Sorry, I'll be about 10 minutes late.

Text: (empty)
Said: my site, kakao dot com, spelled k a k a p o
New text: kakapo.com

Text: Thanks for the files. I will look at them tomorrow and send notes by Friday.
Said: shorter
New text: Thanks, I'll send notes by Friday.

Text: kkapo.com
Said: one more A between the two Ks
New text: kakapo.com

Text: (empty)
Said: the name Clara
New text: Clara

Text: Clara
Said: no, with a K
New text: Klara

Text: Running late, the bus broke down.
Said: more polite
New text: Sorry, I am running late.

Text: Sorry, I am running late.
Said: no, keep the bus part
New text: Sorry, I am running late, the bus broke down."""


# Letters spoken one by one come through as "k a k a p o" or "K-A-K-A-P-O".
SPELLED = re.compile(r"\b[A-Za-z](?:[\s,.-]+[A-Za-z]\b){2,}")


def join_spelled(said: str) -> str:
    """ "spelled k a k a p o" -> "spelled "kakapo" (letter by letter)": done in
    code, since the model is unreliable at gluing letters. Three or more
    single letters in a row, so "I a" and such are left alone."""
    return SPELLED.sub(lambda m: '"' + re.sub(r"[^A-Za-z]", "", m.group()) + '" (spelled letter by letter)', said)


def rewrite(text: str, said: str, history: list[tuple[str, str, str]] = (),
            session: ClaudeSession | None = None) -> str:
    """The box's new text from the model, or raises. history: the earlier
    turns of this session, (text before, said, text after), so "the previous
    one" means something. A Claude session remembers the turns it has seen
    itself, so it gets the history only on its first turn (after a restart)."""
    convo = "".join(f"Text: {a or '(empty)'}\nSaid: {b}\nNew text: {c or '(empty)'}\n\n" for a, b, c in history)
    turn = f"Text: {text or '(empty)'}\nSaid: {join_spelled(said)}\nNew text:"
    if BACKEND == "claude":
        own = session is None                   # a one-off: closed after this turn
        session = session or ClaudeSession()
        try:
            out = session.ask((f"This conversation so far:\n\n{convo}" if convo and not session.turns else "") + turn)
        finally:
            if own:
                session.close()
    else:
        out = ask_ollama(f"{SYSTEM}\n\nThis conversation so far:\n\n{convo}{turn}")
    out = out.removeprefix("New text:").strip()
    if len(out) > 4 and out.startswith("**") and out.endswith("**"):
        out = out[2:-2].strip()                  # Haiku sometimes bolds a one-word answer
    return "" if out == "(empty)" else out


class ClaudeSession:
    """One Claude Code CLI process for a whole compose session: started when
    Create is pressed (so it is warm by the time you stop talking), fed one
    message per turn over stream-json, killed when the panel closes. No tools,
    no MCP servers, no settings or hooks, nothing saved. A turn that doesn't
    finish in TURN_TIMEOUT kills it; the next turn starts a new one."""

    TURN_TIMEOUT = 120

    def __init__(self) -> None:
        self.turns = 0
        self.events: queue.Queue = queue.Queue()
        self.proc = subprocess.Popen(
            [CLAUDE, "-p", "--model", MODEL, "--tools", "", "--no-session-persistence",
             "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}', "--setting-sources", "",
             "--system-prompt", SYSTEM,
             "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, cwd=os.path.expanduser("~"))
        threading.Thread(target=self.read, daemon=True).start()

    def read(self) -> None:
        for line in self.proc.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                pass
        self.events.put(None)        # it exited

    def ask(self, prompt: str) -> str:
        try:
            self.proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            self.close()
            raise RuntimeError(f"claude: {exc}") from exc
        end = time.monotonic() + self.TURN_TIMEOUT
        while True:
            try:
                ev = self.events.get(timeout=max(0.1, end - time.monotonic()))
            except queue.Empty:
                self.close()
                raise TimeoutError(f"claude: no answer in {self.TURN_TIMEOUT} s") from None
            if ev is None:
                self.close()
                raise RuntimeError("claude exited")
            if ev.get("type") == "result":
                self.turns += 1
                if ev.get("is_error") or ev.get("subtype") != "success":
                    raise RuntimeError(f"claude: {ev.get('subtype')} {str(ev.get('result'))[:200]}")
                return (ev.get("result") or "").strip()

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        if self.alive:
            self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def ask_ollama(prompt: str) -> str:
    """One user message, not a system prompt: Gemma only thinks properly that way."""
    body = json.dumps({
        "model": MODEL, "stream": False, "think": True, "keep_alive": "5m",
        "options": {"temperature": 0, "num_ctx": 16384},   # room for the session and the thinking
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(OLLAMA + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as r:
        return json.load(r)["message"]["content"].strip()


def clipboard() -> bytes | None:
    try:
        r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=2, check=False)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def set_clipboard(data: bytes) -> None:
    try:
        subprocess.run(["wl-copy"], input=data, timeout=2, check=False)
    except Exception as exc:
        log.warning("wl-copy: %s", exc)


def load_recent() -> list[str]:
    try:
        with open(RECENT_FILE) as f:
            items = json.load(f)
        return [t for t in items if isinstance(t, str) and t][:RECENT_KEPT]
    except (OSError, ValueError):
        return []


def save_recent(items: list[str]) -> None:
    try:
        os.makedirs(os.path.dirname(RECENT_FILE), exist_ok=True)
        with open(RECENT_FILE + ".tmp", "w") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(RECENT_FILE + ".tmp", RECENT_FILE)
    except OSError as exc:
        log.warning("compose recent: %s", exc)


class Compose:
    def __init__(self, m) -> None:
        self.m = m
        self.open = False
        self.recording = False
        self.busy = False            # a transcript or the model on its way
        self.draft = ""              # what the box should hold (our part of it)
        self.shown = ""              # what we've put in the box so far
        self.original = ""           # L2 + Create: the box's text before we started
        self.whole = False           # L2 + Create: the draft is the box's whole text
        self.undo: list[str] = []
        self.history: list[tuple[str, str, str]] = []   # (text before, said, text after), this session
        self.prompt = ""             # the last thing said
        self.error = ""
        self.saved_clip: bytes | None = None   # the clipboard before we borrowed it
        self.ops: list[tuple] = []   # box edits for tick to send, in order
        self.wait_until = 0.0        # tick holds the next op until then (clipboard settling)
        self.gen = 0                 # bumps on close, so a late answer for a dropped draft is ignored
        self.recent = load_recent()  # finished texts, newest first
        self.session: ClaudeSession | None = None   # the model, kept running while the panel is open
        self.pick = 0                # the highlighted one

    # --- the panel ------------------------------------------------------------

    def state(self) -> str:
        return json.dumps({
            "state": "listening" if self.recording else "thinking" if self.busy
                     else "error" if self.error else "ready",
            "prompt": self.prompt, "draft": self.draft, "error": self.error,
            "undo": bool(self.undo), "recent": self.recent, "pick": self.pick,
            "buttons": profiles.active.buttons()})

    def show(self) -> None:
        if not self.open:
            self.open = True
            self.pick = 0
            self.m.shell.send(PLUGIN, ["summon", PLUGIN, self.state()])
        else:
            self.m.shell.send(PLUGIN, ["call", PLUGIN, "update", self.state()])

    def close(self) -> None:
        if self.recording:
            self.recording = False
            threading.Thread(target=stop_return, daemon=True).start()   # dropped, not typed
        self.open = self.busy = self.whole = False
        self.gen += 1
        self.draft = self.shown = self.original = self.prompt = self.error = ""
        self.undo, self.history = [], []
        if self.session:
            threading.Thread(target=self.session.close, daemon=True).start()
            self.session = None
        self.m.shell.send(PLUGIN, ["hide", PLUGIN])
        self.ops.append(("restore",))    # the clipboard, after any edits still queued

    # --- the box ----------------------------------------------------------------

    def put(self, text: str) -> None:
        """Queue the edits that turn what's in the box into `text`."""
        if text == self.shown:
            return
        if self.saved_clip is None:
            self.saved_clip = clipboard()
        if self.whole:
            self.ops.append(("keys", [CTRL, e.KEY_A]))
            self.ops.append(("paste", text) if text else ("keys", [e.KEY_BACKSPACE]))
        else:
            keep = len(os.path.commonprefix([self.shown, text]))
            if len(self.shown) > keep:
                self.ops.append(("back", len(self.shown) - keep))
            if len(text) > keep:
                self.ops.append(("paste", text[keep:]))
        self.shown = text

    def tick(self) -> None:
        """Send queued box edits, a few at a time, from the input loop."""
        now = time.monotonic()
        while self.ops and now >= self.wait_until:
            op = self.ops[0]
            if op[0] == "back":
                n = min(op[1], BACKSPACES_PER_TICK)
                for _ in range(n):
                    self.m.out.tap([e.KEY_BACKSPACE])
                if n < op[1]:
                    self.ops[0] = ("back", op[1] - n)
                    return
            elif op[0] == "keys":
                self.m.out.tap(op[1])
            elif op[0] == "paste" and len(op) == 2:
                set_clipboard(op[1].encode())
                self.ops[0] = ("paste", op[1], "copied")
                self.wait_until = now + CLIP_WAIT
                return
            elif op[0] == "paste":
                self.m.out.tap([SUPER, e.KEY_V])
                self.wait_until = now + CLIP_WAIT   # it reads the clipboard after the keys
            elif op[0] == "restore" and self.saved_clip is not None and not self.open:
                set_clipboard(self.saved_clip)
                self.saved_clip = None
            self.ops.pop(0)

    # --- buttons --------------------------------------------------------------

    def create(self, down: bool, load: bool = False) -> None:
        """Create pressed or let go. load = L2 held: start from the box's text."""
        if not ENABLED or self.m.talk.active:
            return
        if down and not self.recording and not self.busy:
            if load and not self.open:
                self.load()
            self.recording = True
            self.error = ""
            dictate("start")
            if BACKEND == "claude" and not (self.session and self.session.alive):
                try:
                    self.session = ClaudeSession()   # warms up while you talk
                except OSError as exc:
                    log.warning("compose: can't start claude: %s", exc)
            self.show()
        elif not down and self.recording:
            self.recording, self.busy = False, True
            self.show()
            threading.Thread(target=self.listen, args=(self.gen,), daemon=True).start()

    def load(self) -> None:
        """Select all and copy (Omarchy's universal copy), then read it back.
        Waits on the input loop, once, when the panel opens."""
        self.saved_clip = clipboard()
        set_clipboard(b"")
        self.m.out.tap([CTRL, e.KEY_A])
        self.m.out.tap([SUPER, e.KEY_C])
        time.sleep(CLIP_WAIT)
        text = (clipboard() or b"").decode(errors="replace")
        self.whole = True
        self.draft = self.shown = self.original = text

    def button(self, code, down: bool) -> bool:
        """Face buttons while the panel shows. Everything else goes on as usual."""
        if not self.open or code not in (e.BTN_SOUTH, e.BTN_WEST, e.BTN_EAST, e.BTN_NORTH):
            return False
        if not down:
            return True
        if code == e.BTN_EAST:                          # put the box back as it was
            self.put(self.original)
            self.close()
            self.m.flash.show("○", "Put back", plain=True)
        elif code == e.BTN_NORTH and self.undo and not self.busy:
            self.draft = self.undo.pop()
            self.put(self.draft)
            self.show()
        elif code == e.BTN_WEST and self.recent and not self.busy and not self.recording:
            self.use_recent()
        elif code == e.BTN_SOUTH and not self.busy and not self.recording:
            self.remember(self.draft)
            self.close()                                # done: the box already has it
        return True

    def dpad(self, axis: str, value: int, prev: int) -> None:
        """D-pad ←/→ moves the highlight across the recent texts; the D-pad
        sends no arrow keys while the panel shows."""
        if axis == "x" and value and value != prev and self.recent:
            self.pick = (self.pick + value) % len(self.recent)
            self.show()

    def use_recent(self) -> None:
        """□: the highlighted recent text goes into the draft (after what's there)."""
        item = self.recent[self.pick]
        new = item if not self.draft else self.draft.rstrip() + " " + item
        self.history.append((self.draft, f"(picked from recent: {item})", new))
        self.undo.append(self.draft)
        self.draft = new
        self.put(new)
        self.show()

    def remember(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.recent = [text] + [t for t in self.recent if t != text][:RECENT_KEPT - 1]
        save_recent(self.recent)

    # --- the work, on a thread ------------------------------------------------

    def listen(self, gen: int) -> None:
        said = stop_return()
        if gen != self.gen:
            return
        if not said:
            self.busy = False
            self.error = "Didn't catch that"
            self.show()
            return
        self.prompt = said
        self.show()
        try:
            t0 = time.monotonic()
            new = rewrite(self.draft, said, self.history, self.session)
            log.info("compose: %.2fs %r -> %r", time.monotonic() - t0, said, new)
        except Exception as exc:
            log.warning("compose model failed: %s", exc)
            if self.session and gen == self.gen:
                self.session.close()             # hung or dead: the next turn starts a fresh one
                self.session = None
            new = ""
            self.error = f"{MODEL} didn't answer"
        if gen != self.gen:
            return
        if not self.error:
            self.history.append((self.draft, said, new))
        if not self.error and new != self.draft:
            self.undo.append(self.draft)
            self.draft = new
            self.put(new)
        self.busy = False
        self.show()
