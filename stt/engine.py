"""Vosk-based dictation engine.

Runs entirely on-device in a dedicated worker thread so the GUI never blocks.
A single audio stream is opened for the whole session; one worker is spawned
per dictation session and is released (thread + stream + recognizer) when the
session ends, either manually or after a configured silence timeout.
"""

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from config import DEFAULT_STT_SAMPLE_RATE
from utils.i18n import t

try:
    import sounddevice as sd
    import vosk
    SOUNDDEVICE_OK = True
except Exception:  # pragma: no cover - protects the whole app from a broken install
    sd = None
    vosk = None
    SOUNDDEVICE_OK = False

BLOCKSIZE = 2000  # ~125 ms at 16 kHz; keeps manual stop responsive


def _ascii_safe_path(model_path: str) -> str:
    """Convert a Unicode Windows path to its 8.3 short form.

    Vosk's C++ loader cannot open model files located under a path that
    contains non-ASCII characters (e.g. Cyrillic), so it is converted to the
    short (ASCII) path via GetShortPathNameW. Falls back to the original path
    if the conversion is unavailable or fails.
    """
    if not model_path or not any(ord(ch) > 127 for ch in model_path):
        return model_path
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(
            model_path, buffer, 32768)
        if length and buffer.value:
            return buffer.value
    except Exception:
        pass
    return model_path


def model_is_valid(model_path: str) -> bool:
    """True if ``model_path`` looks like a usable Vosk model directory."""
    path = Path(model_path or "")
    if not path.is_dir():
        return False
    if (path / "am" / "final.mdl").is_file():
        return True
    if (path / "conf" / "mfcc.conf").is_file():
        return True
    return False


def list_microphones():
    """Return ``[(index, name)]`` for every available input device."""
    if not SOUNDDEVICE_OK:
        return []
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    result = []
    for index, device in enumerate(devices):
        try:
            channels = int(device.get("max_input_channels", 0) or 0)
        except Exception:
            channels = 0
        if channels > 0:
            result.append((index, str(device.get("name", f"Device {index}"))))
    return result


def device_exists(name: str) -> bool:
    return any(dev_name == name for _, dev_name in list_microphones())


def _classify_audio_error(exc: Exception) -> str:
    """Map a sounddevice exception to a stable error key."""
    msg = str(exc).lower()
    if "deviceunavailable" in msg or "error opening inputstream" in msg:
        return "mic_busy"
    if "invalidargument" in msg or "invaliddevice" in msg or "invalid device" in msg:
        return "mic_not_found"
    if "invalidsamplerate" in msg or "sample rate" in msg:
        return "sample_rate"
    return "audio_error"


def _parse_vosk_text(payload: str) -> str:
    try:
        import json
        obj = json.loads(payload or "{}")
        text = obj.get("text") or obj.get("partial") or ""
        return str(text).strip()
    except Exception:
        return ""


class SpeechWorker(QObject):
    """Runs one dictation session. Move to a QThread and call :meth:`run`."""

    started = Signal()
    partial = Signal(str)
    result = Signal(str)
    finished = Signal()
    error = Signal(str, str)

    def __init__(self, model_path, microphone="", silence_timeout=1.5,
                 sample_rate=DEFAULT_STT_SAMPLE_RATE, parent=None):
        super().__init__(parent)
        self._model_path = model_path
        self._microphone = microphone or ""
        self._silence_timeout = float(silence_timeout or 1.5)
        self._sample_rate = int(sample_rate or DEFAULT_STT_SAMPLE_RATE)
        self._stop_event = threading.Event()
        self._stream = None
        self._recognizer = None

    def request_stop(self):
        self._stop_event.set()

    def stop(self):
        self.request_stop()

    # ------------------------------------------------------------- pipeline

    def run(self):
        if not SOUNDDEVICE_OK:
            self.error.emit(t("stt.deps_missing"),
                            "vosk / sounddevice are not available")
            self.finished.emit()
            return

        # Vosk cannot load models from non-ASCII (e.g. Cyrillic) paths on
        # Windows — use the 8.3 short path for loading.
        model_path = _ascii_safe_path(self._model_path)
        if not model_is_valid(model_path):
            self.error.emit(t("stt.model_not_found"), self._model_path or "")
            self.finished.emit()
            return

        try:
            model = vosk.Model(model_path)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(t("stt.model_load_error"), str(exc))
            self.finished.emit()
            return
        self._recognizer = vosk.KaldiRecognizer(model, self._sample_rate)

        try:
            device_index = self._resolve_device()
        except RuntimeError as exc:
            self.error.emit(t("stt.mic_not_found"), str(exc))
            self.finished.emit()
            return

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate, channels=1, dtype="int16",
                device=device_index, blocksize=BLOCKSIZE)
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(t("stt." + _classify_audio_error(exc)), str(exc))
            self.finished.emit()
            return

        self.started.emit()
        parts = []
        last_partial = ""
        saw_speech = False
        last_speech_time = time.monotonic()
        noise_floor = 200.0

        try:
            while not self._stop_event.is_set():
                try:
                    data, _overflow = self._stream.read(BLOCKSIZE)
                except Exception as exc:  # noqa: BLE001 - mic lost mid-recording
                    self.error.emit(t("stt.mic_lost"), str(exc))
                    break

                rms = float(_rms(data))
                # Adaptive noise floor: only tracked while the input is quiet,
                # so a loud first block is always treated as speech.
                if not saw_speech or rms < _threshold_for(noise_floor):
                    noise_floor = 0.9 * noise_floor + 0.1 * rms
                threshold = _threshold_for(noise_floor)
                is_speech = rms > threshold
                now = time.monotonic()
                if is_speech:
                    saw_speech = True
                    last_speech_time = now

                if self._stop_event.is_set():
                    break

                if self._recognizer.AcceptWaveform(data.tobytes()):
                    chunk = _parse_vosk_text(self._recognizer.Result())
                    if chunk:
                        parts.append(chunk)
                last_partial = _parse_vosk_text(self._recognizer.PartialResult())
                if last_partial:
                    self.partial.emit(self._joined(parts, last_partial))

                # Automatic stop once the user has been silent long enough.
                if saw_speech and not is_speech:
                    if now - last_speech_time >= self._silence_timeout:
                        break
        except Exception as exc:  # noqa: BLE001 - never leave the UI hanging
            self.error.emit(t("stt.audio_error"), str(exc))
        finally:
            self._close_stream()

        # Flush any pending utterance when the session ends.
        tail = _parse_vosk_text(self._recognizer.FinalResult())
        if tail:
            parts.append(tail)
        self.result.emit(" ".join(p for p in parts if p).strip())
        self.finished.emit()

    # -------------------------------------------------------------- helpers

    def _resolve_device(self):
        """Return the PortAudio device index, default input when unset."""
        name = (self._microphone or "").strip()
        if not name:
            return None
        for index, dev_name in list_microphones():
            if dev_name == name:
                return index
        raise RuntimeError(f"microphone '{name}' not found")

    @staticmethod
    def _joined(parts, partial):
        base = " ".join(p for p in parts if p)
        if base:
            return (base + " " + partial).strip()
        return partial.strip()

    def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass


def _threshold_for(noise_floor: float) -> float:
    """VAD threshold derived from the tracked noise floor."""
    return max(300.0, min(12000.0, noise_floor * 4.0 + 200.0))


def _rms(data) -> float:
    """Root-mean-square of an int16 numpy array (for voice activity)."""
    if data is None or len(data) == 0:
        return 0.0
    samples = data.ravel()
    if samples.size == 0:
        return 0.0
    squares = samples.astype("float64") ** 2
    return float((squares.mean()) ** 0.5)
