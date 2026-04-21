"""Voice-to-text support using sounddevice + macOS SFSpeechRecognizer."""
from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

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
    recognizer.recognitionTask(with: req) { res, _ in
        if let res = res, res.isFinal {
            transcription = res.bestTranscription.formattedString
        }
        done = true
    }
}

while !done {
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


def transcribe_file(wav_path: str) -> str | None:
    """Transcribe a WAV file. Blocks. Returns text or None on failure."""
    bin_path = _binary_path()
    if not bin_path.exists():
        if not _compile_binary():
            return None
    try:
        result = subprocess.run(
            [str(bin_path), wav_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
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
