"""TTS synthesis backends behind one interface.

Each provider loads its model(s) once and exposes:
  .available            -> bool
  .languages            -> list[str]
  .voice_id(lang)       -> str            (used in the cache key)
  .synthesize(text,lang)-> (np.float32 mono samples, sample_rate)

Keeping the engine behind a common interface makes it swappable — the project
rule favours open, self-hosted, provider-abstracted models. Default is Kokoro
(Apache-2.0); Piper stays available as a lighter alternative."""
import logging
import os

import numpy as np

from . import config

logger = logging.getLogger("jingo-tts")


class KokoroProvider:
    """Kokoro-82M (Apache-2.0). One ONNX model + one combined voice pack cover
    all languages; a language is selected per-call by voice id + lang code."""

    def __init__(self):
        self._k = None
        self._voices = dict(config.KOKORO_VOICES)
        try:
            from kokoro_onnx import Kokoro
            self._k = Kokoro(config.KOKORO_MODEL_PATH, config.KOKORO_VOICES_PATH)
            logger.info("kokoro loaded; voices=%s", self._voices)
        except Exception as exc:  # pragma: no cover - deployment-only path
            logger.error("kokoro load failed: %s", exc)

    @property
    def available(self):
        return self._k is not None

    @property
    def languages(self):
        return sorted(self._voices.keys())

    def voice_id(self, lang):
        return self._voices.get(lang) or self._voices.get(config.DEFAULT_LANG)

    def synthesize(self, text, lang):
        use_lang = lang if lang in self._voices else config.DEFAULT_LANG
        espeak_lang = config.KOKORO_LANG_CODES.get(use_lang, use_lang)
        samples, sr = self._k.create(
            text, voice=self.voice_id(lang), speed=1.0, lang=espeak_lang
        )
        return np.asarray(samples, dtype=np.float32).squeeze(), int(sr)


class PiperProvider:
    """Piper (MIT). One ONNX voice model per language."""

    def __init__(self):
        self._voices = {}
        self._names = dict(config.PIPER_VOICES)
        try:
            from piper import PiperVoice
            for lang, name in config.PIPER_VOICES.items():
                onnx = os.path.join(config.PIPER_VOICE_DIR, name + ".onnx")
                self._voices[lang] = PiperVoice.load(onnx, onnx + ".json")
                logger.info("piper loaded %s for lang=%s", name, lang)
        except Exception as exc:  # pragma: no cover - deployment-only path
            logger.error("piper load failed: %s", exc)

    @property
    def available(self):
        return bool(self._voices)

    @property
    def languages(self):
        return sorted(self._voices.keys())

    def voice_id(self, lang):
        return self._names.get(lang) or self._names.get(config.DEFAULT_LANG)

    def _voice(self, lang):
        return self._voices.get(lang) or self._voices.get(config.DEFAULT_LANG)

    def synthesize(self, text, lang):
        pcm = bytearray()
        sr = 22050
        for chunk in self._voice(lang).synthesize(text):
            pcm += chunk.audio_int16_bytes
            sr = chunk.sample_rate
        arr = np.frombuffer(bytes(pcm), dtype=np.int16).astype(np.float32) / 32768.0
        return arr, int(sr)


def build_provider():
    """Construct the provider named by TTS_ENGINE (default kokoro)."""
    if config.TTS_ENGINE == "piper":
        return PiperProvider()
    return KokoroProvider()
