"""Text-to-speech: VOICEVOX synthesis + system-voice fallback.

This module owns the ``subprocess`` and ``shutil`` imports the TTS tests patch
(``zenbuji.tts.subprocess``/``zenbuji.tts.shutil``). ``speak`` calls
``voicevox_synthesize``/``_play_wav`` as bare in-module names so patching them
here lands.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request

VOICEVOX_DEFAULT_HOST = "127.0.0.1:50021"
VOICEVOX_DEFAULT_SPEAKER = 3  # ずんだもん (Zundamon), normal style
_AUDIO_PLAYERS = ("pw-play", "paplay", "aplay", "ffplay")


def voicevox_synthesize(text: str, host: str, speaker: int,
                        speed: float = 1.0) -> bytes:
    """Return WAV audio for `text` from a local VOICEVOX engine.

    Two-step HTTP API: POST /audio_query builds the synthesis parameters, POST
    /synthesis renders them to a WAV. `speed` overrides the query's speedScale
    (1.0 = normal; VOICEVOX accepts ~0.5–2.0). Raises (URLError/timeout) if the
    engine isn't reachable — callers treat that as "no VOICEVOX".
    """
    base = f"http://{host}"
    params = urllib.parse.urlencode({"text": text, "speaker": speaker})
    req = urllib.request.Request(f"{base}/audio_query?{params}", method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        audio_query = resp.read()
    if speed and speed != 1.0:
        data = json.loads(audio_query)
        data["speedScale"] = speed
        audio_query = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/synthesis?speaker={speaker}", data=audio_query,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _play_wav(wav: bytes) -> None:
    """Play in-memory WAV bytes through the first available audio player."""
    player = next((p for p in _AUDIO_PLAYERS if shutil.which(p)), None)
    if not player or not wav:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav)
        path = f.name
    try:
        if player == "ffplay":
            argv = ["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet", path]
        elif player == "aplay":
            argv = ["aplay", "-q", path]
        else:  # pw-play / paplay
            argv = [player, path]
        subprocess.run(argv, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def speak(text: str, cfg: dict, block: bool = False) -> None:
    """Read Japanese text aloud (best-effort, non-blocking by default).

    Feed the hiragana reading for the clearest pronunciation. The engine is
    chosen by cfg["tts_engine"]:
      * "voicevox" — synthesize via the local VOICEVOX engine (natural neural)
      * "system"   — spd-say (speech-dispatcher) then espeak-ng (robotic)
      * "auto"     — VOICEVOX if its engine answers, otherwise the system voice
      * "command"  — run cfg["tts_command"] (kept for power users)
      * "off"      — silent
    A non-empty tts_command always wins, whatever the engine, for backwards
    compatibility. With block=True the call waits for playback to finish —
    needed by short-lived CLI runs (e.g. `add --speak`) that would otherwise
    exit and cut the audio off. Never raises: audio is a nicety on top.
    """
    text = (text or "").strip()
    if not text:
        return
    engine = cfg.get("tts_engine", "auto")
    if engine == "off":
        return

    speed = float(cfg.get("tts_speed", 1.0) or 1.0)

    def run():
        try:
            command = cfg.get("tts_command")
            if command or engine == "command":
                if not command:
                    return
                parts = shlex.split(command)
                argv = ([p.replace("{text}", text) for p in parts]
                        if any("{text}" in p for p in parts) else [*parts, text])
                subprocess.run(argv, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return

            if engine in ("voicevox", "auto"):
                try:
                    wav = voicevox_synthesize(
                        text, cfg.get("voicevox_host", VOICEVOX_DEFAULT_HOST),
                        cfg.get("voicevox_speaker", VOICEVOX_DEFAULT_SPEAKER),
                        speed)
                    _play_wav(wav)
                    return
                except Exception:  # engine unreachable / synthesis failed
                    if engine == "voicevox":
                        return  # explicit choice — don't surprise with a robot
                    # "auto" falls through to the system voice below.

            if shutil.which("spd-say"):
                # spd-say rate is -100..100 (0 = normal); map the speed factor.
                rate = max(-100, min(100, round((speed - 1.0) * 100)))
                subprocess.run(["spd-say", "-w", "-r", str(rate), "-l", "ja",
                                "--", text], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("espeak-ng"):
                # espeak-ng default is ~175 wpm; scale it by the speed factor.
                wpm = max(80, min(450, round(175 * speed)))
                subprocess.run(["espeak-ng", "-s", str(wpm), "-v", "ja",
                                "--", text], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001 — audio must never break a lookup
            pass

    if block:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
