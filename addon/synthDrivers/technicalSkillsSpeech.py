# Technical Skills Speech - unified NVDA synthesizer driver
# Copyright (C) 2026 Technical Skills Solutions
#
# This module is the single NVDA-facing driver. The original engine drivers are
# packaged as private backend modules under names beginning with an underscore,
# so NVDA does not list them as separate synthesizers.

from __future__ import annotations

import logging
import threading
import unicodedata
from collections import OrderedDict, deque

import core
import config
import languageHandler
import synthDriverHandler
from configobj import ConfigObj
from io import StringIO
from logHandler import log
from speech.commands import (
    BreakCommand,
    CharacterModeCommand,
    IndexCommand,
    LangChangeCommand,
    PhonemeCommand,
    PitchCommand,
    RateCommand,
    VolumeCommand,
)
from synthDriverHandler import (
    SynthDriver as BaseSynthDriver,
    VoiceInfo,
    synthDoneSpeaking,
    synthIndexReached,
)

addonHandler = None


def _rootLanguage(language):
    if not language:
        return None
    return str(language).replace("-", "_").split("_", 1)[0].lower()


def _scriptLanguage(character):
    """Return a language hint for a character, or None for neutral characters."""
    if not character or character.isspace() or not character.isalpha():
        return None
    name = unicodedata.name(character, "")
    if "DEVANAGARI" in name:
        return "hi"
    if "BENGALI" in name:
        return "bn"
    if "GURMUKHI" in name:
        return "pa"
    if "GUJARATI" in name:
        return "gu"
    if "TAMIL" in name:
        return "ta"
    if "TELUGU" in name:
        return "te"
    if "KANNADA" in name:
        return "kn"
    if "MALAYALAM" in name:
        return "ml"
    if "ARABIC" in name:
        return "ar"
    if "CYRILLIC" in name:
        return "ru"
    if "HEBREW" in name:
        return "he"
    if "GREEK" in name:
        return "el"
    if "HIRAGANA" in name or "KATAKANA" in name:
        return "ja"
    if "HANGUL" in name:
        return "ko"
    if "CJK UNIFIED IDEOGRAPH" in name or "IDEOGRAPH" in name:
        return "zh"
    if "LATIN" in name:
        return "en"
    return None


def _splitByScript(text, fallbackLanguage="en"):
    """Split text into contiguous script runs while keeping neutral marks attached."""
    runs = []
    currentLanguage = None
    currentText = []
    for character in text:
        detected = _scriptLanguage(character)
        if detected is None:
            if currentLanguage is None:
                currentLanguage = fallbackLanguage
            currentText.append(character)
            continue
        if currentLanguage is None:
            currentLanguage = detected
        elif detected != currentLanguage:
            if currentText:
                runs.append((currentLanguage, "".join(currentText)))
            currentLanguage = detected
            currentText = []
        currentText.append(character)
    if currentText:
        runs.append((currentLanguage or fallbackLanguage, "".join(currentText)))
    return runs


class SynthDriver(BaseSynthDriver):
    """One NVDA SynthDriver that serializes and routes speech to two engines."""

    name = "technicalSkillsSpeech"
    description = "Technical Skills Speech (Eloquence + Vocalizer Expressive 2)"

    supportedSettings = (
        BaseSynthDriver.VoiceSetting(),
        BaseSynthDriver.VariantSetting(),
        BaseSynthDriver.RateSetting(),
        BaseSynthDriver.PitchSetting(),
        BaseSynthDriver.VolumeSetting(),
        BaseSynthDriver.InflectionSetting(),
    )
    supportedCommands = {
        IndexCommand,
        CharacterModeCommand,
        LangChangeCommand,
        BreakCommand,
        PitchCommand,
        RateCommand,
        VolumeCommand,
        PhonemeCommand,
    }
    supportedNotifications = {synthIndexReached, synthDoneSpeaking}

    @classmethod
    def check(cls):
        """Offer the unified driver when at least one backend can initialize."""
        eloquenceAvailable = False
        vocalizerAvailable = False
        try:
            from synthDrivers._tss_eloquence_backend import SynthDriver as EloquenceDriver
            eloquenceAvailable = bool(EloquenceDriver.check())
        except Exception:
            log.debug("Technical Skills Speech: Eloquence check failed", exc_info=True)
        try:
            from synthDrivers._tss_vocalizer_backend import SynthDriver as VocalizerDriver
            vocalizerAvailable = bool(VocalizerDriver.check())
        except Exception:
            log.debug("Technical Skills Speech: Vocalizer check failed", exc_info=True)
        log.info(
            "Technical Skills Speech backend availability: Eloquence=%s Vocalizer=%s",
            eloquenceAvailable,
            vocalizerAvailable,
        )
        return eloquenceAvailable or vocalizerAvailable

    def __init__(self):
        self._lock = threading.RLock()
        self._segments = deque()
        self._activeBackendName = None
        self._busy = False
        self._terminated = False
        self._voice = "auto"
        self._rate = 50
        self._pitch = 50
        self._volume = 100
        self._inflection = 50
        self._variant = "1"
        self._eloquence = None
        self._vocalizer = None
        self._backendErrors = {}

        # Both backends are initialized once at driver startup to avoid a cold
        # start delay on the first language switch. Speech itself is serialized.
        try:
            from synthDrivers._tss_eloquence_backend import SynthDriver as EloquenceDriver
            self._eloquence = EloquenceDriver()
            self._eloquence.initSettings()
            self._eloquence._tss_event_callback = self._onBackendEvent
        except Exception as error:
            self._backendErrors["eloquence"] = error
            log.error("Technical Skills Speech: Eloquence initialization failed", exc_info=True)
            if self._eloquence is not None:
                try:
                    self._eloquence.terminate()
                except Exception:
                    log.debug("Error cleaning up failed Eloquence initialization", exc_info=True)
            self._eloquence = None

        try:
            from synthDrivers._tss_vocalizer_backend import SynthDriver as VocalizerDriver
            self._vocalizer = VocalizerDriver()
            # The unified router performs language detection. Avoid a second,
            # independent detector inside the Vocalizer backend.
            try:
                from synthDrivers._tss_vocalizer_backend import _config as vocalizerConfig
                vocalizerConfig.vocalizerConfig["autoLanguageSwitching"]["useUnicodeLanguageDetection"] = False
            except Exception:
                log.debug("Could not disable the backend's secondary language detector", exc_info=True)
            self._vocalizer.initSettings()
            self._vocalizer._tss_event_callback = self._onBackendEvent
        except Exception as error:
            self._backendErrors["vocalizer"] = error
            log.error("Technical Skills Speech: Vocalizer initialization failed", exc_info=True)
            if self._vocalizer is not None:
                try:
                    self._vocalizer.terminate()
                except Exception:
                    log.debug("Error cleaning up failed Vocalizer initialization", exc_info=True)
            self._vocalizer = None

        if self._eloquence is None and self._vocalizer is None:
            raise RuntimeError("Neither Eloquence nor Vocalizer Expressive 2 could be initialized")

        self._initVoiceProfiles()
        try:
            self._lastSettingsTarget = self._resolveTarget(languageHandler.getLanguage())
        except Exception:
            self._lastSettingsTarget = ("eloquence", str(self._eloquence.voice)) if self._eloquence else ("vocalizer", str(self._vocalizer.voice))
        self._applyVoiceProfile(self._lastSettingsTarget)
        log.info(
            "Technical Skills Speech initialized: Eloquence=%s Vocalizer=%s",
            self._eloquence is not None,
            self._vocalizer is not None,
        )

    def _initVoiceProfiles(self):
        """Create persistent per-engine/per-voice settings in NVDA config."""
        speechSection = config.conf["speech"]
        if not speechSection.isSet("technicalSkillsSpeech"):
            speechSection["technicalSkillsSpeech"] = {}
        tssSection = speechSection["technicalSkillsSpeech"]
        spec = ConfigObj(StringIO("""[voiceProfiles]
[[__many__]]
rate = integer(default=50, min=0, max=100)
pitch = integer(default=50, min=0, max=100)
volume = integer(default=100, min=0, max=100)
inflection = integer(default=50, min=0, max=100)
variant = string(default="1")
"""), list_values=False, encoding="UTF-8")
        tssSection.spec.update(spec)
        if not tssSection.isSet("voiceProfiles"):
            tssSection["voiceProfiles"] = {}
        self._voiceProfiles = tssSection["voiceProfiles"]

    @staticmethod
    def _profileKey(target):
        engine, voiceId = target
        safeVoice = "".join(
            character if character.isalnum() or character in "_.-" else "_%04X" % ord(character)
            for character in str(voiceId)
        )
        return "%s__%s" % (engine, safeVoice)

    def _getProfile(self, target=None):
        target = target or self._getSettingsTarget()
        key = self._profileKey(target)
        if not self._voiceProfiles.isSet(key):
            self._voiceProfiles[key] = {}
        profile = self._voiceProfiles[key]
        defaults = {
            "rate": 50,
            "pitch": 50,
            "volume": 100,
            "inflection": 50,
            "variant": "1",
        }
        for name, default in defaults.items():
            if not profile.isSet(name):
                profile[name] = default
        return profile

    def _getSettingsTarget(self):
        target = getattr(self, "_lastSettingsTarget", None)
        if target:
            return target
        try:
            return self._resolveTarget(languageHandler.getLanguage())
        except Exception:
            if self._eloquence is not None:
                return ("eloquence", str(self._eloquence.voice))
            if self._vocalizer is not None:
                return ("vocalizer", str(self._vocalizer.voice))
            return ("eloquence", "default")

    def _applyVoiceProfile(self, target):
        """Apply only the selected target voice's own settings to its engine."""
        if not target:
            return
        engineName, voiceId = target
        backend = self._eloquence if engineName == "eloquence" else self._vocalizer
        if backend is None:
            return
        profile = self._getProfile(target)
        try:
            if str(backend.voice) != str(voiceId):
                backend.voice = str(voiceId)
            if engineName == "eloquence":
                # Eloquence's ECI parameters are engine-global. Reapply the
                # selected voice's own profile every time routing changes.
                try:
                    backend.variant = str(profile.get("variant", "1"))
                except Exception:
                    log.debug("Could not apply Eloquence variant profile", exc_info=True)
                backend.rate = int(profile.get("rate", 50))
                backend.pitch = int(profile.get("pitch", 50))
                backend.volume = int(profile.get("volume", 100))
                backend.inflection = int(profile.get("inflection", 50))
            else:
                # Vocalizer keeps one engine instance per voice; its parameters
                # are set only on the voice selected for this segment.
                backend.rate = int(profile.get("rate", 50))
                backend.pitch = int(profile.get("pitch", 50))
                backend.volume = int(profile.get("volume", 100))
                try:
                    variant = str(profile.get("variant", "1"))
                    if variant in backend.availableVariants:
                        backend.variant = variant
                except Exception:
                    pass
        except Exception:
            log.warning("Could not apply settings profile for %s voice %s", engineName, voiceId, exc_info=True)

    def _setProfileValue(self, name, value, target=None):
        target = target or self._getSettingsTarget()
        profile = self._getProfile(target)
        profile[name] = value
        # Do not broadcast settings to both engines. Only the voice whose
        # profile is being edited is changed.
        engineName, voiceId = target
        backend = self._eloquence if engineName == "eloquence" else self._vocalizer
        if backend is None:
            return
        try:
            if str(backend.voice) != str(voiceId):
                backend.voice = str(voiceId)
            if name in ("rate", "pitch", "volume", "inflection", "variant"):
                if name == "inflection" and engineName != "eloquence":
                    return
                if name == "variant":
                    if engineName == "eloquence" or str(value) in backend.availableVariants:
                        backend.variant = str(value)
                else:
                    setattr(backend, name, int(value))
        except Exception:
            log.debug("Could not update %s for %s voice %s", name, engineName, voiceId, exc_info=True)

    def _getAvailableVoices(self):
        voices = OrderedDict()
        voices["auto"] = VoiceInfo("auto", "Automatic language detection", None)
        if self._eloquence is not None:
            try:
                for voiceId, info in self._eloquence.availableVoices.items():
                    key = "eloquence:" + str(voiceId)
                    voices[key] = VoiceInfo(key, "Eloquence - " + info.displayName, info.language)
            except Exception:
                log.warning("Could not enumerate Eloquence voices", exc_info=True)
        if self._vocalizer is not None:
            try:
                for voiceId, info in self._vocalizer.availableVoices.items():
                    key = "vocalizer:" + str(voiceId)
                    voices[key] = VoiceInfo(key, "Vocalizer - " + info.displayName, info.language)
            except Exception:
                log.warning("Could not enumerate Vocalizer voices", exc_info=True)
        return voices

    def _get_voice(self):
        return self._voice

    def _set_voice(self, value):
        value = str(value or "auto")
        if value != "auto" and value not in self.availableVoices:
            log.warning("Ignoring unavailable Technical Skills Speech voice %r", value)
            value = "auto"
        self._voice = value
        try:
            if value.startswith("eloquence:") and self._eloquence is not None:
                self._lastSettingsTarget = ("eloquence", value.split(":", 1)[1])
            elif value.startswith("vocalizer:") and self._vocalizer is not None:
                self._lastSettingsTarget = ("vocalizer", value.split(":", 1)[1])
            else:
                self._lastSettingsTarget = self._resolveTarget(languageHandler.getLanguage())
            self._applyVoiceProfile(self._lastSettingsTarget)
        except Exception:
            log.warning("Could not apply selected voice %r", value, exc_info=True)
            self._voice = "auto"

    def _getAvailableVariants(self):
        target = self._getSettingsTarget()
        engineName, _voiceId = target
        backend = self._eloquence if engineName == "eloquence" else self._vocalizer
        if backend is not None:
            try:
                return backend.availableVariants
            except Exception:
                pass
        return OrderedDict((str(i), VoiceInfo(str(i), name)) for i, name in {
            1: "Reed", 2: "Shelly", 3: "Bobby", 4: "Rocko",
            5: "Glen", 6: "Sandy", 7: "Grandma", 8: "Grandpa",
        }.items())

    def _get_variant(self):
        target = self._getSettingsTarget()
        profile = self._getProfile(target)
        engineName, _voiceId = target
        backend = self._eloquence if engineName == "eloquence" else self._vocalizer
        if backend is not None:
            try:
                return str(backend.variant)
            except Exception:
                pass
        return str(profile.get("variant", "1"))

    def _set_variant(self, value):
        target = self._getSettingsTarget()
        engineName, _voiceId = target
        backend = self._eloquence if engineName == "eloquence" else self._vocalizer
        value = str(value or "1")
        if backend is not None:
            try:
                if value not in backend.availableVariants:
                    log.warning("Ignoring unavailable variant %r for %s", value, engineName)
                    return
            except Exception:
                if engineName == "eloquence" and value not in {str(i) for i in range(1, 9)}:
                    value = "1"
        self._variant = value
        self._setProfileValue("variant", value, target)

    def _get_rate(self):
        return int(self._getProfile().get("rate", 50))

    def _set_rate(self, value):
        self._rate = max(0, min(100, int(value)))
        self._setProfileValue("rate", self._rate)

    def _get_pitch(self):
        return int(self._getProfile().get("pitch", 50))

    def _set_pitch(self, value):
        self._pitch = max(0, min(100, int(value)))
        self._setProfileValue("pitch", self._pitch)

    def _get_volume(self):
        return int(self._getProfile().get("volume", 100))

    def _set_volume(self, value):
        self._volume = max(0, min(100, int(value)))
        self._setProfileValue("volume", self._volume)

    def _get_inflection(self):
        return int(self._getProfile().get("inflection", 50))

    def _set_inflection(self, value):
        self._inflection = max(0, min(100, int(value)))
        self._setProfileValue("inflection", self._inflection)

    def _eloquenceVoiceForLanguage(self, language):
        if self._eloquence is None:
            return None
        try:
            from synthDrivers._tss_eloquence_backend import LANGUAGE_TO_VOICE_ID, PRIMARY_LANGUAGE_TO_VOICE_IDS
            normalized = _rootLanguage(language)
            if not normalized:
                return None
            candidates = PRIMARY_LANGUAGE_TO_VOICE_IDS.get(normalized, [])
            exact = LANGUAGE_TO_VOICE_ID.get(str(language).replace("_", "-").lower())
            candidate = exact or (candidates[0] if candidates else None)
            if candidate is not None and str(candidate) in self._eloquence.availableVoices:
                return str(candidate)
        except Exception:
            log.debug("Eloquence language-to-voice lookup failed", exc_info=True)
        return None

    def _vocalizerVoiceForLanguage(self, language):
        if self._vocalizer is None:
            return None
        try:
            voice = self._vocalizer.getVoiceNameForLanguage(_rootLanguage(language))
            if voice and voice in self._vocalizer.availableVoices:
                return voice
        except Exception:
            log.debug("Vocalizer language-to-voice lookup failed", exc_info=True)
        return None

    def _resolveTarget(self, language):
        # An explicitly selected voice overrides automatic routing.
        if self._voice.startswith("eloquence:") and self._eloquence is not None:
            return ("eloquence", self._voice.split(":", 1)[1])
        if self._voice.startswith("vocalizer:") and self._vocalizer is not None:
            return ("vocalizer", self._voice.split(":", 1)[1])

        language = _rootLanguage(language) or _rootLanguage(languageHandler.getLanguage()) or "en"
        vocalizerVoice = self._vocalizerVoiceForLanguage(language)
        eloquenceVoice = self._eloquenceVoiceForLanguage(language)

        # Hindi uses the bundled Neel voice when available. For other locales,
        # prefer a matching Vocalizer locale, then Eloquence's built-in voices.
        if language == "hi" and vocalizerVoice:
            return ("vocalizer", vocalizerVoice)
        if vocalizerVoice and language not in ("en",):
            return ("vocalizer", vocalizerVoice)
        if eloquenceVoice:
            return ("eloquence", eloquenceVoice)
        if vocalizerVoice:
            return ("vocalizer", vocalizerVoice)
        if self._eloquence is not None:
            defaultVoice = self._eloquenceVoiceForLanguage("en")
            if defaultVoice:
                return ("eloquence", defaultVoice)
            return ("eloquence", self._eloquence.voice)
        if self._vocalizer is not None:
            return ("vocalizer", self._vocalizer.voice)
        raise RuntimeError("No speech engine is available")

    def _splitSequence(self, speechSequence):
        segments = []
        activeTarget = None
        activeItems = []
        currentLanguage = None

        def flush():
            nonlocal activeTarget, activeItems
            if activeTarget is not None and activeItems:
                segments.append((activeTarget, activeItems))
            activeTarget = None
            activeItems = []

        def add(item, language):
            nonlocal activeTarget, activeItems
            target = self._resolveTarget(language)
            if target != activeTarget:
                flush()
                activeTarget = target
            activeItems.append(item)

        fallbackLanguage = _rootLanguage(languageHandler.getLanguage()) or "en"
        for item in speechSequence:
            if isinstance(item, LangChangeCommand):
                currentLanguage = _rootLanguage(item.lang)
                routedLanguage = currentLanguage or fallbackLanguage
                add(item, routedLanguage)
            elif isinstance(item, str):
                if currentLanguage:
                    add(item, currentLanguage)
                else:
                    runs = _splitByScript(item, fallbackLanguage)
                    for language, text in runs:
                        add(text, language)
            else:
                add(item, currentLanguage or fallbackLanguage)
        flush()
        return segments

    def _onBackendEvent(self, backend, event, index=None):
        backendName = "eloquence" if backend is self._eloquence else "vocalizer"
        if event == "index":
            with self._lock:
                if backendName != self._activeBackendName or self._terminated:
                    return
            synthIndexReached.notify(synth=self, index=index)
            return
        if event == "done":
            with self._lock:
                if backendName != self._activeBackendName or self._terminated:
                    return
                self._activeBackendName = None
            core.callLater(0, self._dispatchNext)

    def speak(self, speechSequence):
        if self._terminated:
            return
        segments = self._splitSequence(speechSequence)
        with self._lock:
            self._segments.extend(segments)
            # Keep an end marker for each NVDA speak() call. NVDA may enqueue
            # several sequences while a previous backend is still speaking;
            # each call still receives its own completion notification.
            self._segments.append(None)
            shouldStart = not self._busy
            if shouldStart:
                self._busy = True
        if shouldStart:
            self._dispatchNext()

    def _dispatchNext(self):
        with self._lock:
            if self._terminated:
                self._segments.clear()
                self._activeBackendName = None
                self._busy = False
                return
            if self._activeBackendName is not None:
                return
            if not self._segments:
                self._busy = False
                return
            segment = self._segments.popleft()
            if segment is None:
                self._activeBackendName = None
                hasMore = bool(self._segments)
                self._busy = hasMore
                finished = True
            else:
                finished = False
                target, sequence = segment
                self._activeBackendName = target[0]

        if finished:
            # NVDA's done-speaking notification applies to the whole queued
            # stream, not to an intermediate boundary while more speech is
            # still waiting. Notify only when the queue is truly empty.
            if hasMore:
                core.callLater(0, self._dispatchNext)
            else:
                synthDoneSpeaking.notify(synth=self)
            return

        backendName, voiceId = segment[0]
        sequence = segment[1]
        backend = self._eloquence if backendName == "eloquence" else self._vocalizer
        if backend is None:
            log.warning("Requested backend %s is unavailable; skipping a speech segment", backendName)
            with self._lock:
                self._activeBackendName = None
            core.callLater(0, self._dispatchNext)
            return

        try:
            target = (backendName, str(voiceId))
            self._lastSettingsTarget = target
            # Restore this exact voice's profile immediately before speaking.
            # Eloquence's ECI parameters are global to its process, so applying
            # the selected voice profile at each route boundary is essential.
            self._applyVoiceProfile(target)
            backend.speak(sequence)
        except Exception:
            log.error("Technical Skills Speech failed in %s segment", backendName, exc_info=True)
            with self._lock:
                self._activeBackendName = None
            core.callLater(0, self._dispatchNext)

    def cancel(self):
        with self._lock:
            self._segments.clear()
            self._activeBackendName = None
            self._busy = False
        for backend in (self._eloquence, self._vocalizer):
            if backend is not None:
                try:
                    backend.cancel()
                except Exception:
                    log.debug("Error cancelling speech backend", exc_info=True)

    def pause(self, switch):
        with self._lock:
            activeName = self._activeBackendName
        backend = self._eloquence if activeName == "eloquence" else self._vocalizer if activeName == "vocalizer" else None
        if backend is not None:
            try:
                backend.pause(switch)
            except Exception:
                log.debug("Could not change backend pause state", exc_info=True)

    def terminate(self):
        self.cancel()
        with self._lock:
            self._terminated = True
        for backend in (self._eloquence, self._vocalizer):
            if backend is not None:
                try:
                    backend.terminate()
                except Exception:
                    log.error("Error terminating speech backend", exc_info=True)
        self._eloquence = None
        self._vocalizer = None
        super().terminate()
