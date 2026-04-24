"""Voice-to-text support using sounddevice + macOS SFSpeechRecognizer."""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

try:
    import sounddevice as sd  # type: ignore
    import numpy as np  # type: ignore
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False

# --- timing constants (seconds) ---
RELEASE_DELAY = 0.20   # no space-repeat within this window → key released
REPEAT_DELAY = 0.60    # initial hold: auto-repeat fires before this → hold confirmed

SAMPLE_RATE = 16_000
CHANNELS = 1

# --- embedded Swift transcriber source ---
_SWIFT_SOURCE = r"""
import Foundation
import Speech

guard CommandLine.arguments.count > 1 else {
    fputs("Usage: transcribe <wav>\n", stderr); exit(1)
}

var done = false
var transcription: String? = nil

SFSpeechRecognizer.requestAuthorization { status in
    guard status == .authorized else {
        fputs("Speech recognition not authorized\n", stderr)
        done = true; return
    }
    guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable else {
        fputs("Speech recognizer unavailable\n", stderr)
        done = true; return
    }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let req = SFSpeechURLRecognitionRequest(url: url)
    req.shouldReportPartialResults = false
    if #available(macOS 13.0, *) { req.requiresOnDeviceRecognition = true }
    recognizer.recognitionTask(with: req) { res, err in
        if let res = res, res.isFinal {
            transcription = res.bestTranscription.formattedString
        }
        // Only mark done when the task is complete: final result or error.
        if res?.isFinal == true || err != nil {
            done = true
        }
    }
}

let deadline = Date(timeIntervalSinceNow: 8.0)
while !done && Date() < deadline {
    RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.1))
}

if let text = transcription { print(text); exit(0) }
exit(1)
"""


def _binary_path() -> Path:
    from platformdirs import user_data_dir
    return Path(user_data_dir("chronicle")) / "transcribe"


def _compile_binary() -> bool:
    """Compile the Swift transcriber binary. Returns True on success."""
    swiftc = "/usr/bin/swiftc"
    if not os.path.exists(swiftc):
        return False
    bin_path = _binary_path()
    bin_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".swift", delete=False, mode="w") as f:
        f.write(_SWIFT_SOURCE)
        swift_path = f.name

    try:
        sdk = subprocess.check_output(["xcrun", "--show-sdk-path"], stderr=subprocess.DEVNULL).decode().strip()
        result = subprocess.run(
            [swiftc, swift_path, "-o", str(bin_path), "-sdk", sdk],
            capture_output=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.unlink(swift_path)
        except OSError:
            pass


def is_available() -> bool:
    """True if voice input can be attempted on this system."""
    return _SD_AVAILABLE and os.path.exists("/usr/bin/swiftc")


def warmup() -> None:
    """Pre-compile the transcriber binary if needed. Call once in a daemon thread."""
    if not is_available():
        return
    if not _binary_path().exists():
        _compile_binary()


TRANSCRIBE_TIMEOUT = 10.0  # seconds — Swift side has its own 8s deadline


def _log(msg: str) -> None:
    """Append one line to ~/Library/Logs/chronicle-voice.log. Never raises."""
    try:
        path = Path.home() / "Library" / "Logs" / "chronicle-voice.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def transcribe_file(wav_path: str) -> str | None:
    """Transcribe a WAV file. Blocks up to TRANSCRIBE_TIMEOUT. Returns text or None."""
    bin_path = _binary_path()
    if not bin_path.exists():
        if not _compile_binary():
            _log("transcribe: no binary, compile failed")
            return None

    # Redirect Swift stdout to a temp file rather than a pipe. On macOS the
    # Speech framework's dispatch queues can hold the write end of a stdout
    # pipe open past the binary's exit(), which makes communicate() block
    # well past its timeout. wait() on a file-backed stdout isn't affected.
    out_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    out_file.close()
    out_path = out_file.name

    out_fh = None
    try:
        _log(f"transcribe: launching {bin_path} {wav_path}")
        out_fh = open(out_path, "wb")
        proc = subprocess.Popen(
            [str(bin_path), wav_path],
            stdout=out_fh,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setsid,
            close_fds=True,
        )
        out_fh.close()
        out_fh = None
        try:
            rc = proc.wait(timeout=TRANSCRIBE_TIMEOUT)
            _log(f"transcribe: exited rc={rc}")
            if rc == 0:
                with open(out_path, "rb") as f:
                    text = f.read().decode(errors="replace").strip()
                _log(f"transcribe: got {len(text)} chars")
                return text or None
        except subprocess.TimeoutExpired:
            _log("transcribe: timeout — SIGKILL process group")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _log("transcribe: process still alive after SIGKILL (!)")
    except Exception as e:
        _log(f"transcribe: exception {e!r}")
    finally:
        if out_fh is not None:
            try:
                out_fh.close()
            except OSError:
                pass
        try:
            os.unlink(out_path)
        except OSError:
            pass
    return None


class VoiceRecorder:
    """Non-blocking microphone recorder backed by a queue."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._stream = None

    def start(self) -> bool:
        """Start recording. Returns False if sounddevice is unavailable."""
        if not _SD_AVAILABLE:
            return False
        self._q = queue.Queue()
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                callback=lambda indata, *_: self._q.put(indata.copy()),
            )
            self._stream.start()
            return True
        except Exception:
            self._stream = None
            return False

    def stop_and_save(self) -> str | None:
        """Stop recording and save to a temp WAV. Returns path or None if empty."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        chunks: list = []
        try:
            while True:
                chunks.append(self._q.get_nowait())
        except queue.Empty:
            pass

        if not chunks:
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(np.concatenate(chunks).tobytes())
        return tmp.name


class ViewVoiceHoldHandler:
    """Hold-space → record → release → transcribe → on_transcript(text).

    Used by main views (no text field to insert into). Short space taps are
    swallowed; holds (detected via key auto-repeat inside REPEAT_DELAY) start
    recording. Any non-space key during recording aborts and discards.
    """

    def __init__(
        self,
        widget,
        on_transcript: Callable[[str], None],
    ) -> None:
        self._widget = widget
        self._on_transcript = on_transcript
        self._vr: Optional[VoiceRecorder] = VoiceRecorder() if is_available() else None
        self._pending = False
        self._recording = False
        self._repeat_timer = None
        self._release_timer = None

    @property
    def available(self) -> bool:
        return self._vr is not None

    def handle_key(self, event) -> bool:
        """Return True if the event was consumed (caller should stop it)."""
        if self._vr is None:
            return False
        if event.key == "space":
            return self._handle_space()
        self._cancel()
        return False

    def _handle_space(self) -> bool:
        if self._recording:
            if self._release_timer:
                self._release_timer.stop()
            self._release_timer = self._widget.set_timer(
                RELEASE_DELAY, self._on_release
            )
            return True

        if not self._pending:
            self._pending = True
            self._repeat_timer = self._widget.set_timer(
                REPEAT_DELAY, self._on_no_repeat
            )
            return True

        # Second space within REPEAT_DELAY → hold confirmed
        self._pending = False
        if self._repeat_timer:
            self._repeat_timer.stop()
            self._repeat_timer = None
        if self._vr and self._vr.start():
            self._recording = True
            try:
                self._widget.app.set_voice_state("recording")
            except Exception:
                pass
            self._release_timer = self._widget.set_timer(
                RELEASE_DELAY, self._on_release
            )
        return True

    def _cancel(self) -> None:
        """Non-space key pressed — abort pending or recording state."""
        if self._pending:
            self._pending = False
            if self._repeat_timer:
                self._repeat_timer.stop()
                self._repeat_timer = None
        if self._recording:
            self._recording = False
            if self._release_timer:
                self._release_timer.stop()
                self._release_timer = None
            wav = self._vr.stop_and_save() if self._vr else None
            if wav:
                try:
                    os.unlink(wav)
                except OSError:
                    pass
            try:
                self._widget.app.set_voice_state("idle")
            except Exception:
                pass

    def _on_no_repeat(self) -> None:
        self._pending = False
        self._repeat_timer = None

    def _on_release(self) -> None:
        self._release_timer = None
        if not self._recording:
            return
        self._recording = False
        wav = self._vr.stop_and_save() if self._vr else None
        app = self._widget.app
        if not wav:
            try:
                app.set_voice_state("idle")
            except Exception:
                pass
            return
        try:
            app.set_voice_state("transcribing")
        except Exception:
            pass
        threading.Thread(
            target=self._transcribe, args=(wav, app), daemon=True
        ).start()

    def _transcribe(self, wav_path: str, app) -> None:
        text: Optional[str] = None
        try:
            text = transcribe_file(wav_path)
        except Exception:
            pass
        try:
            os.unlink(wav_path)
        except OSError:
            pass
        try:
            app.call_from_thread(app.set_voice_state, "idle")
        except Exception:
            pass
        if text:
            try:
                app.call_from_thread(self._on_transcript, text)
            except Exception:
                pass
        else:
            try:
                app.call_from_thread(app.notify, "Transcription failed.", severity="warning")
            except Exception:
                pass
