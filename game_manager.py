"""Selects the active KAXMOK livestream game."""
import threading
import word_hunt
import code_breaker
import mystery_box

_LOCK=threading.RLock()
_ACTIVE="off"
_STARTED=False

def start():
    global _STARTED
    if _STARTED:
        return
    _STARTED=True
    word_hunt.start()
    code_breaker.start()
    mystery_box.start()

def switch(name):
    global _ACTIVE
    name=(name or "").strip().casefold()
    aliases={"whoami":"whoami","who":"whoami","codebreaker":"codebreaker","code":"codebreaker","mystery":"mystery","box":"mystery","off":"off"}
    if name not in aliases:
        return False
    with _LOCK:
        _ACTIVE=aliases[name]
    print(f"[GAME] Active game changed to {_ACTIVE}.",flush=True)
    return True

def handle_guess(author,message):
    with _LOCK:
        active=_ACTIVE
    if active=="mystery":
        if mystery_box.handle_command(author,message):
            return True
        return mystery_box.handle_guess(author,message)
    if active=="whoami":
        return word_hunt.handle_guess(author,message)
    if active=="codebreaker":
        return code_breaker.handle_guess(author,message)
    return False

def render_overlay(frame_bytes):
    with _LOCK:
        active=_ACTIVE
    if active=="mystery":
        return mystery_box.render_overlay(frame_bytes)
    if active=="whoami":
        return word_hunt.render_overlay(frame_bytes)
    if active=="codebreaker":
        return code_breaker.render_overlay(frame_bytes)
    return frame_bytes

def active_game():
    with _LOCK:
        return _ACTIVE
