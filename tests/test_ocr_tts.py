"""OCR and text-to-speech — heavy deps (manga-ocr, audio players, VOICEVOX) are
mocked so these run anywhere, offline and silent."""

import json
import urllib.request

import zenbuji


# --- a fake urlopen returning queued responses ------------------------------ #
class _Resp:
    def __init__(self, payload):
        self._b = payload

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


# --- OCR -------------------------------------------------------------------- #
def test_ocr_missing_file_returns_note(tmp_path):
    text, notes = zenbuji.ocr_image_to_text(str(tmp_path / "nope.png"), {})
    assert text == "" and notes


def test_ocr_success(tmp_path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")
    monkeypatch.setattr(zenbuji.ocr, "_manga_ocr", lambda: (lambda p: " 日本語 "))
    text, notes = zenbuji.ocr_image_to_text(str(img), {})
    assert text == "日本語" and notes == []


def test_ocr_not_installed(tmp_path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")

    def raise_import():
        raise ImportError

    monkeypatch.setattr(zenbuji.ocr, "_manga_ocr", raise_import)
    text, notes = zenbuji.ocr_image_to_text(str(img), {})
    assert text == "" and notes


def test_ocr_unknown_backend_warns(tmp_path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(zenbuji.ocr, "_manga_ocr", lambda: (lambda p: "text"))
    text, notes = zenbuji.ocr_image_to_text(str(img), {"ocr_backend": "weird"})
    assert text == "text"
    assert any("weird" in n or "manga" in n.lower() for n in notes)


# --- VOICEVOX synthesis (HTTP mocked) --------------------------------------- #
def test_voicevox_synthesize_two_step(monkeypatch):
    responses = [b'{"speedScale": 1.0}', b"WAVDATA"]
    reqs = []

    def fake(req, timeout=None):
        reqs.append(req)
        return _Resp(responses.pop(0))

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    wav = zenbuji.voicevox_synthesize("こ", "127.0.0.1:50021", 3, 1.0)
    assert wav == b"WAVDATA"
    assert "/audio_query" in reqs[0].full_url
    assert "/synthesis" in reqs[1].full_url


def test_voicevox_synthesize_applies_speed(monkeypatch):
    responses = [b'{"speedScale": 1.0}', b"W"]
    sent = {}

    def fake(req, timeout=None):
        if req.data:
            sent["query"] = req.data
        return _Resp(responses.pop(0))

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    zenbuji.voicevox_synthesize("こ", "h", 3, 1.5)
    assert json.loads(sent["query"])["speedScale"] == 1.5


# --- speak() engine dispatch (all side effects mocked) ---------------------- #
def test_speak_off_is_silent(monkeypatch):
    calls = []
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", lambda *a, **k: calls.append(a))
    zenbuji.speak("こ", {"tts_engine": "off"}, block=True)
    assert calls == []


def test_speak_empty_is_silent(monkeypatch):
    calls = []
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", lambda *a, **k: calls.append(a))
    zenbuji.speak("   ", {"tts_engine": "auto"}, block=True)
    assert calls == []


def test_speak_custom_command_with_placeholder(monkeypatch):
    calls = []
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", lambda argv, **k: calls.append(argv))
    zenbuji.speak("こ", {"tts_engine": "command", "tts_command": "mytts {text}"},
                  block=True)
    assert calls[0] == ["mytts", "こ"]


def test_speak_custom_command_wins_and_appends_text(monkeypatch):
    calls = []
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", lambda argv, **k: calls.append(argv))
    zenbuji.speak("こ", {"tts_engine": "system", "tts_command": "mytts"}, block=True)
    assert calls[0] == ["mytts", "こ"]


def test_speak_voicevox_plays_wav(monkeypatch):
    played = []
    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize", lambda *a, **k: b"WAV")
    monkeypatch.setattr(zenbuji.tts, "_play_wav", lambda wav: played.append(wav))
    zenbuji.speak("こ", {"tts_engine": "voicevox"}, block=True)
    assert played == [b"WAV"]


def test_speak_voicevox_engine_silent_when_unreachable(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")

    def fail(*a, **k):
        raise AssertionError("should not reach the system voice")

    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize", boom)
    monkeypatch.setattr(zenbuji.tts, "_play_wav", fail)
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", fail)
    monkeypatch.setattr(zenbuji.tts.shutil, "which", lambda p: None)
    zenbuji.speak("こ", {"tts_engine": "voicevox"}, block=True)  # silent, no fallback


def test_speak_auto_falls_back_to_system_voice(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")

    calls = []
    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize", boom)
    monkeypatch.setattr(zenbuji.tts.shutil, "which",
                        lambda p: "/usr/bin/spd-say" if p == "spd-say" else None)
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", lambda argv, **k: calls.append(argv))
    zenbuji.speak("こ", {"tts_engine": "auto"}, block=True)
    assert calls and calls[0][0] == "spd-say"


def test_play_wav_invokes_first_available_player(monkeypatch):
    monkeypatch.setattr(zenbuji.tts.shutil, "which",
                        lambda p: f"/usr/bin/{p}" if p == "pw-play" else None)
    calls = []
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", lambda argv, **k: calls.append(argv))
    zenbuji._play_wav(b"RIFFdata")
    assert calls and calls[0][0] == "pw-play"


def test_play_wav_no_player_is_noop(monkeypatch):
    monkeypatch.setattr(zenbuji.tts.shutil, "which", lambda p: None)
    calls = []
    monkeypatch.setattr(zenbuji.tts.subprocess, "run", lambda *a, **k: calls.append(a))
    zenbuji._play_wav(b"data")
    assert calls == []


# --- phrase_speaker: render once, replay many (the practice drill) ---------- #
def test_phrase_speaker_synthesizes_once_then_replays(monkeypatch):
    synth, played = [], []
    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize",
                        lambda *a, **k: (synth.append(a), b"WAV")[1])
    monkeypatch.setattr(zenbuji.tts, "_play_wav", lambda wav: played.append(wav))
    play = zenbuji.tts.phrase_speaker("てすと", {"tts_engine": "voicevox"})
    play(block=True)
    play(block=True)
    play(block=True)
    assert len(synth) == 1            # neural synthesis happened exactly once
    assert played == [b"WAV"] * 3     # but the cached WAV replayed each retype


def test_phrase_speaker_off_is_silent(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not synthesize when TTS is off")

    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize", boom)
    monkeypatch.setattr(zenbuji.tts, "_play_wav", boom)
    zenbuji.tts.phrase_speaker("てすと", {"tts_engine": "off"})(block=True)


# --- on-disk WAV cache (TTS_CACHE_DIR redirected to tmp by the autouse fixture) #
def test_cached_synthesize_hits_disk_second_time(monkeypatch):
    synth = []
    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize",
                        lambda *a, **k: (synth.append(a), b"WAV")[1])
    w1 = zenbuji.tts._cached_synthesize("こ", "h", 3, 1.0)
    w2 = zenbuji.tts._cached_synthesize("こ", "h", 3, 1.0)
    assert w1 == w2 == b"WAV"
    assert len(synth) == 1            # second call read the cached file


def test_cached_synthesize_keys_on_voice_and_speed(monkeypatch):
    synth = []
    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize",
                        lambda *a, **k: (synth.append(a), b"W")[1])
    zenbuji.tts._cached_synthesize("こ", "h", 3, 1.0)
    zenbuji.tts._cached_synthesize("こ", "h", 3, 1.2)   # different speed
    zenbuji.tts._cached_synthesize("こ", "h", 8, 1.0)   # different speaker
    assert len(synth) == 3            # distinct keys, no false cache hits


def test_speak_voicevox_goes_through_disk_cache(monkeypatch):
    synth, played = [], []
    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize",
                        lambda *a, **k: (synth.append(a), b"WAV")[1])
    monkeypatch.setattr(zenbuji.tts, "_play_wav", lambda wav: played.append(wav))
    zenbuji.speak("こ", {"tts_engine": "voicevox"}, block=True)
    zenbuji.speak("こ", {"tts_engine": "voicevox"}, block=True)
    assert played == [b"WAV", b"WAV"]   # played both times
    assert len(synth) == 1              # but synthesized only once


def test_wav_cache_evicts_oldest(monkeypatch):
    monkeypatch.setattr(zenbuji.tts, "_WAV_CACHE_CAP", 3)
    monkeypatch.setattr(zenbuji.tts, "voicevox_synthesize", lambda *a, **k: b"W")
    for i in range(6):
        zenbuji.tts._cached_synthesize(f"t{i}", "h", 3, 1.0)
    files = list(zenbuji.paths.TTS_CACHE_DIR.glob("*.wav"))
    assert len(files) <= 3              # bounded; oldest evicted
