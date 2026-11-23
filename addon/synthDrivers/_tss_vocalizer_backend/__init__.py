import queue
import threading
import unicodedata
import os
import re
from collections import OrderedDict
from ctypes import *

import config
import nvwave
import languageHandler
import addonHandler
import speech
from speech.commands import IndexCommand, CharacterModeCommand, LangChangeCommand, PitchCommand, RateCommand, VolumeCommand, BreakCommand, SpeechCommand
from synthDriverHandler import SynthDriver, LanguageInfo, VoiceInfo, synthIndexReached, synthDoneSpeaking
from autoSettingsUtils.driverSetting import DriverSetting
from autoSettingsUtils.utils import StringParameterInfo
from logHandler import log

from . import ve2
from .ve2.veTypes import *
from . import languageDetection
from . import _config

addonHandler.initTranslation()

BIN_DICT_CONTENT_TYPE = "application/edct-bin-dictionary"
TEXT_RULESET_CONTENT_TYPE = "application/x-vocalizer-rettt+text"
_voiceDicts = {}
_tuningDataDir = os.path.join(os.path.dirname(__file__), "tuningData")

# Vocalizer's raw text-normalization control blocks abbreviation expansion.
# Limit it to short Devanagari words, then restore normal mode after each word
# so ordinary dates, numbers, punctuation and long phrases keep normal TN.
_SHORT_DEVANAGARI_TOKEN = re.compile(r"[\u0900-\u097F\uA8E0-\uA8FF]+")

def _protectShortHindiTokens(text, maxLetters=3):
    def protect(match):
        token = match.group(0)
        letterCount = sum(
            1 for character in token
            if unicodedata.category(character).startswith("L")
        )
        if 0 < letterCount <= maxLetters:
            return "\x1b\\tn=raw\\" + token + "\x1b\\tn=normal\\"
        return token
    return _SHORT_DEVANAGARI_TOKEN.sub(protect, text)

VOICE_PARAMETERS = [
	(VE_PARAM_VOICE_OPERATING_POINT, "variant", str),
	(VE_PARAM_SPEECHRATE, "rate", int),
	(VE_PARAM_PITCH, "pitch", int),
	(VE_PARAM_VOLUME, "volume", int),
	(VE_PARAM_WAITFACTOR, "waitfactor", int),
]

def getResourcePaths():
	# Technical Skills Speech embeds the Neel resource tree in the same add-on.
	# The add-on root is two levels above this hidden backend package.
	addonRoot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
	resourcePaths = []
	if os.path.isdir(os.path.join(addonRoot, "hii", "speech")):
		resourcePaths.append(addonRoot)
	resourcePaths.extend(
		addon.path for addon in addonHandler.getRunningAddons()
		if addon.name.startswith("vocalizer-expressive2-voice")
	)
	programdata = os.getenv("PROGRAMDATA")
	if programdata:
		# Looking for Vocalizer voice data from Freedom Scientific
		for version in ("2.2", "21"):
			path = os.path.join(programdata, "Freedom Scientific", "VocalizerExpressive", version, "languages")
			try:
				if os.listdir(path):
					resourcePaths.append(path)
			except IOError:
				pass
	return resourcePaths

def getAvailableResources():
	resources = OrderedDict()
	for l in ve2.getLanguageList():
		langCode = ve2.getLocaleNameFromTLW(l.szLanguageTLW.decode("utf-8"))
		if langCode is None: # Unknown language, skip it
			continue
		languageInfo = LanguageInfo(langCode)

		if not languageInfo.displayName:
			languageInfo.displayName = l.szLanguage
		resources[languageInfo] = []

		for v in ve2.getVoiceList(l.szLanguage):
			name = f'{v.szVoiceName.decode("utf-8")} - {languageInfo.displayName}'
			voiceInfo = VoiceInfo(v.szVoiceName.decode("utf-8"), name, languageInfo.id or None)
			resources[languageInfo].append(voiceInfo)

	return resources

class BgThread(threading.Thread):

	def __init__(self, bgQueue):
		super().__init__()
		self._bgQueue = bgQueue
		self.setDaemon(True)
		self.start()

	def run(self):
		while True:
			task = self._bgQueue.get()
			if task is None:
				break
			try:
				task()
			except Exception:
				log.error("Error running task from queue", exc_info=True)
			self._bgQueue.task_done()

pcmBufLen = 8192 # 8 Kb
markBufSize = 100

class VECallback(object):

	def __init__(self, player, isSilence, onIndexReached):
		self._player = player
		self._isSilence = isSilence
		self._onIndexReached = onIndexReached
		# allocate PCM and mark buffers
		self._pcmBuf = (c_byte * pcmBufLen)()
		self._markBuf = (VE_MARKINFO * markBufSize)()

	def __call__(self, instance, userData, message):
		""" Callback to handle assynchronous requests and messages from the synthecizer. """
		try:
			outData = cast(message.contents.pParam, POINTER(VE_OUTDATA))
			messageType = message.contents.eMessage
			if self._isSilence.isSet() and messageType != VE_MSG_ENDPROCESS:
				return NUAN_E_TTS_USERSTOP
			elif messageType == VE_MSG_OUTBUFREQ:
				# Request for storage to put sound and mark data.
				# Here we fill the pointers to our already allocated buffers (on initialize).
				outData.contents.pOutPcmBuf = cast(self._pcmBuf, c_void_p)
				outData.contents.cntPcmBufLen = c_size_t(pcmBufLen)
				outData.contents.pMrkList = cast(self._markBuf, POINTER(VE_MARKINFO))
				outData.contents.cntMrkListLen = c_size_t(markBufSize * sizeof(VE_MARKINFO))
			elif messageType == VE_MSG_OUTBUFDONE:
				# Sound data and mark buffers were produced by vocalizer.
				# Send wave data to be played:
				if outData.contents.cntPcmBufLen > 0:
					data = string_at(outData.contents.pOutPcmBuf, outData.contents.cntPcmBufLen)
					self._player.feed(data)
				# Make sure that the speech is not interrupted by the user
				if self._isSilence.isSet():
					return NUAN_E_TTS_USERSTOP
				# And check for bookmarks
				for i in range(int(outData.contents.cntMrkListLen)):
					if outData.contents.pMrkList[i].eMrkType == VE_MRK_BOOKMARK:
						self._onIndexReached(outData.contents.pMrkList[i].ulMrkId)
		except:
			log.error("Vocalizer callback", exc_info=True)
		return NUAN_OK

class ProcessText2Speech(object):

	def __init__(self, instance, text):
		self._instance = instance
		self._text = text

	def __call__(self):
		ve2.processText2Speech(self._instance, self._text)

class TtsSetParamList(object):

	def __init__(self, instance, *idAndValues):
		self._instance = instance
		self._idAndValues = idAndValues

	@property
	def instance(self):
		return self._instance

	@property
	def idAndValues(self):
		return self._idAndValues

	def __call__(self):
		ve2.setParamList(self._instance, *self._idAndValues)

class DoneSpeaking(object):

	def __init__(self, player, onIndexReached):
		self._player = player
		self._onIndexReached = onIndexReached

	def __call__(self):
		self._player.idle()
		self._onIndexReached(None)

class SynthDriver(SynthDriver):
	name = "vocalizer_expressive2"
	description = "Nuance Vocalizer expressive 2.2"

	supportedSettings = [
		SynthDriver.VoiceSetting(),
		SynthDriver.VariantSetting(),
		SynthDriver.RateSetting(),
		SynthDriver.PitchSetting(),
		SynthDriver.VolumeSetting(),
		DriverSetting("waitfactor", _("&Wait factor"), availableInSettingsRing=True),
		DriverSetting("normalization", _("&Normalization"), availableInSettingsRing=True),
	]
	supportedCommands = {
		IndexCommand,
		CharacterModeCommand,
		LangChangeCommand,
		PitchCommand,
		BreakCommand,
	}
	supportedNotifications = {synthIndexReached, synthDoneSpeaking}

	@classmethod
	def check(cls):
		resources = getResourcePaths()
		if not resources:
			return False
		with ve2.preOpenVocalizer(resources) as success:
			if not success:
				log.debugWarning("Vocalizer not available.", exc_info=True)
			return success

	def __init__(self):
		resources = getResourcePaths()
		if not resources:
			raise RuntimeError("no resources available")
		ve2.initialize(resources)

		self._instanceCache = {}
		self._bgQueue = queue.Queue()
		self._bgThread = BgThread(self._bgQueue)

		try:
			# Audio device used since NVDA 2025.1
			outputDevice = config.conf["audio"]["outputDevice"]
		except KeyError:
			# Older NVDA versions
			outputDevice = config.conf["speech"]["outputDevice"]
		self._player = nvwave.WavePlayer(channels=1, samplesPerSec=22050, bitsPerSample=16, outputDevice=outputDevice)
		self._isSilence = threading.Event()
		self._veCallback = VE_CBOUTNOTIFY(VECallback(self._player, self._isSilence, self._onIndexReached))

		self._resources = getAvailableResources()
		self._languageDetector = languageDetection.LanguageDetector([l.id for l in self._resources])
		self._voice = self.getVoiceNameForLanguage(languageHandler.getLanguage())
		if self._voice is None:
			self._voice = list(self.availableVoices.keys())[0]
		self._normalization = "OFF"

	def _onVoiceTuning(self, instance, voiceName):
		# Ruleset
		rulesetPath = os.path.join(_tuningDataDir, f"{voiceName.lower()}.rules")
		if os.path.exists(rulesetPath):
			with open(rulesetPath, "rb") as f:
				content = f.read()
			log.debug(f"Loading ruleset from {rulesetPath}")
			try:
				ve2.resourceLoad(TEXT_RULESET_CONTENT_TYPE, content, instance)
			except VeError:
				log.warning(f"Error Loading vocalizer rules from {rulesetPath}", exc_info=True)
		# Load custom dictionary if one exists
		if voiceName not in _voiceDicts:
			dictPath = os.path.join(_tuningDataDir, f"{voiceName.lower()}.dcb")
			if os.path.exists(dictPath):
				with open(dictPath, "rb") as f:
					_voiceDicts[voiceName] = f.read()
					log.debug(f"Loading vocalizer dictionary from {dictPath}")
		if voiceName in _voiceDicts:
			try:
				ve2.resourceLoad(BIN_DICT_CONTENT_TYPE, _voiceDicts[voiceName], instance)
			except VeError:
				log.warning("Error loading Vocalizer dictionary.", exc_info=True)

	def getVoiceInstance(self, voiceName):
		try:
			return self._instanceCache[voiceName]
		except KeyError:
			pass
		instance, name = ve2.open(voiceName, self._veCallback)
		log.debug(f"Created synth instance for voice {name}")
		self._onVoiceTuning(instance, name)
		self.onVoiceLoad(name, instance)
		self._instanceCache[name] = instance
		return instance

	def getVoiceNameForLanguage(self, language):
		lang = _config.vocalizerConfig["autoLanguageSwitching"].get(language, None)
		if lang is not None:
			if lang["voice"] in self.availableVoices:
				return lang["voice"]

		for l, voices in self._resources.items():
			if l.id.startswith(language):
				return voices[0].id

	def onVoiceLoad(self, voiceName, instance):
		""" Restores variant and other settings if available, when a voice is loaded."""

		if voiceName in _config.vocalizerConfig['voices']:
			idAndValues = []
			for p, name, t in VOICE_PARAMETERS:
				value = _config.vocalizerConfig['voices'][voiceName].get(name, None)
				if value is not None:
					idAndValues.append((p, t(value)))
			if idAndValues:
				self._bgQueue.put(TtsSetParamList(instance, *idAndValues))

	def onVoiceUnload(self, voiceName, instance):
		""" Saves variant to be restored for each voice."""

		if voiceName not in _config.vocalizerConfig['voices']:
			_config.vocalizerConfig['voices'][voiceName] = {}

		for p, name, t in VOICE_PARAMETERS:
			value = self.getParameter(instance, p, type_=t)
			_config.vocalizerConfig['voices'][voiceName][name] = value

	def saveSettings(self):
		for voiceName, instance in self._instanceCache.items():
			self.onVoiceUnload(voiceName, instance)
		super().saveSettings()

	def loadSettings(self, onlyChanged=False):
		for voiceName, instance in self._instanceCache.items():
			self.onVoiceLoad(voiceName, instance)
		super().loadSettings(onlyChanged)

	def terminate(self):
		self.cancel()
		try:
			for voiceName, instance in self._instanceCache.items():
				ve2.close(instance)
			self._instanceCache.clear()
			ve2.terminate()
		except RuntimeError:
			log.error("Vocalizer terminate", exc_info=True)
		self._bgQueue.put(None)
		self._bgThread.join()
		self._player.close()
		self._veCallback = None

	def speak(self, speechSequence):
		currentInstance = defaultInstance = self.voiceInstance
		currentLanguage = defaultLanguage = self.language
		chunks = []
		hasText = False
		charMode = False

		if _config.vocalizerConfig["autoLanguageSwitching"]["useUnicodeLanguageDetection"]:
			speechSequence = self._languageDetector.add_detected_language_commands(speechSequence, defaultLanguage)

		for command in speechSequence:
			if isinstance(command, str):
				command = command.strip()
				if not command:
					continue
				# If character mode is on use lower case characters
				# Because the synth does not allow to turn off the caps reporting
				if charMode or len(command) == 1:
					command = command.lower()
				# unicode text normalization according to the specified form
				if self._normalization != "OFF":
					command = unicodedata.normalize(self._normalization, command)
				if hasText and not charMode:
					# Previous chunk is the usual text. We need to insert a speech separator
					chunks.append(speech.CHUNK_SEPARATOR)
				# ESC is reserved for Vocalizer's own control sequences. Protect
				# short Hindi words from abbreviation expansion (e.g. रवि -> रविवार,
				# मार -> March, जन -> January) using a narrowly scoped TN raw block.
				# Restore TN normal immediately after each short token.
				safeCommand = command.replace("\x1b", "")
				if str(currentLanguage or "").replace("-", "_").split("_", 1)[0].lower() == "hi":
					safeCommand = _protectShortHindiTokens(safeCommand)
				chunks.append(safeCommand)
				hasText = True
			elif isinstance(command, IndexCommand):
				chunks.append(f"\x1b\\mrk={command.index}\\")
			elif isinstance(command, CharacterModeCommand):
				charMode = command.state
				s = "\x1b\\tn=spell\\" if command.state else "\x1b\\tn=normal\\"
				chunks.append(s)
			elif isinstance(command, LangChangeCommand):
				if command.lang == currentLanguage:
					# Keep on the same voice.
					continue
				if command.lang is None:
					# No language, use default.
					currentInstance = defaultInstance
					currentLanguage = defaultLanguage
					continue
				# Changed language, lets see what we have.
				currentLanguage = command.lang
				newVoiceName = self.getVoiceNameForLanguage(currentLanguage)
				if newVoiceName is None:
					# No voice for this language, use default.
					newInstance = defaultInstance
				else:
					newInstance = self.getVoiceInstance(newVoiceName)
				if newInstance == currentInstance:
					# Same voice, next command.
					continue
				if hasText: # We changed voice, send text we already have to vocalizer.
					self._speak(currentInstance, chunks)
					chunks = []
					hasText = False
				currentInstance = newInstance
			elif isinstance(command, PitchCommand):
				pitch = self.getParameter(currentInstance, VE_PARAM_PITCH)
				pitchOffset = self._percentToParam(command.offset, PITCH_MIN, PITCH_MAX) - PITCH_MIN
				chunks.append(f"\x1b\\pitch={pitch+pitchOffset}\\")
			elif isinstance(command, (RateCommand, VolumeCommand)):
				# Flush preceding text before changing a parameter so the update is
				# ordered with the Vocalizer worker queue and cannot affect earlier audio.
				if hasText:
					self._speak(currentInstance, chunks)
					chunks = []
					hasText = False
				if isinstance(command, RateCommand):
					rateValue = max(0, min(100, int(command.newValue)))
					engineRate = self._percentToParam(rateValue, RATE_MIN, RATE_MAX)
					self._bgQueue.put(TtsSetParamList(currentInstance, (VE_PARAM_SPEECHRATE, engineRate)))
				else:
					volumeValue = max(0, min(100, int(command.newValue)))
					self._bgQueue.put(TtsSetParamList(currentInstance, (VE_PARAM_VOLUME, volumeValue)))
			elif isinstance(command, BreakCommand):
				# Supported range is 1-65535 msec
				breakTime = max(1, min(command.time, 65535))
				chunks.append(f"\x1b\\pause={breakTime}\\")
			elif isinstance(command, SpeechCommand):
				log.debugWarning(f"Unsupported speech command: {command}")
			else:
				log.error(f"Unknown speech: {command}")
		if chunks:
			self._speak(currentInstance, chunks)
		# Restore user-configured baseline settings after sequence-local prosody
		# commands. The worker queue preserves ordering after the final text chunk.
		baseRate = self._percentToParam(self.rate, RATE_MIN, RATE_MAX)
		self._bgQueue.put(TtsSetParamList(currentInstance, (VE_PARAM_SPEECHRATE, baseRate), (VE_PARAM_VOLUME, int(self.volume))))
		self._bgQueue.put(DoneSpeaking(self._player, self._onIndexReached))

	def _speak(self, voiceInstance, chunks):
		text = "".join(chunks)
		self._bgQueue.put(ProcessText2Speech(voiceInstance, text))

	def cancel(self):
		taskList = []
		try:
			while True:
				task = self._bgQueue.get_nowait()
				self._bgQueue.task_done()
				if isinstance(task, (TtsSetParamList, DoneSpeaking)):
					taskList.append(task)
		except queue.Empty:
			pass
		for task in taskList:
			self._bgQueue.put(task)
		self._isSilence.set()
		self._bgQueue.put(self._isSilence.clear)
		self._player.stop()
		self._bgQueue.join()

	def pause(self, switch):
		self._player.pause(switch)

	def _onIndexReached(self, index):
		callback = getattr(self, "_tss_event_callback", None)
		if callback is not None:
			callback(self, "index" if index is not None else "done", index)
		elif index is not None:
			synthIndexReached.notify(synth=self, index=index)
		else:
			synthDoneSpeaking.notify(synth=self)

	def getParameter(self, instance, paramId, type_=int):
		return self.getParameters(instance, (paramId, type_))[0]

	def getParameters(self, instance, *idAndTypes):
		taskList = []
		values = [None] * len(idAndTypes)

		try:
			while True:
				task = self._bgQueue.get_nowait()
				self._bgQueue.task_done()
				taskList.append(task)
		except queue.Empty:
			pass

		for task in filter(lambda t: isinstance(t, TtsSetParamList) and t.instance == instance, taskList):
			for id, value in task.idAndValues:
				for i, p in enumerate(idAndTypes):
					if id == p[0]:
						values[i] = value

		for task in taskList:
			self._bgQueue.put(task)

		if None not in values:
			return values
		return ve2.getParamList(instance, *idAndTypes)

	def _get_voiceInstance(self):
		return self.getVoiceInstance(self.voice)

	def _get_volume(self):
		return self.getParameter(self.voiceInstance, VE_PARAM_VOLUME)

	def _set_volume(self, value):
		self._bgQueue.put(TtsSetParamList(self.voiceInstance, (VE_PARAM_VOLUME, int(value))))

	def _get_rate(self):
		rate = self.getParameter(self.voiceInstance, VE_PARAM_SPEECHRATE)
		return self._paramToPercent(rate, RATE_MIN, RATE_MAX)

	def _set_rate(self, value):
		rate = self._percentToParam(value, RATE_MIN, RATE_MAX)
		self._bgQueue.put(TtsSetParamList(self.voiceInstance, (VE_PARAM_SPEECHRATE, rate)))

	def _get_pitch(self):
		pitch = self.getParameter(self.voiceInstance, VE_PARAM_PITCH)
		return self._paramToPercent(pitch, PITCH_MIN, PITCH_MAX)

	def _set_pitch(self, value):
		pitch = self._percentToParam(value, PITCH_MIN, PITCH_MAX)
		self._bgQueue.put(TtsSetParamList(self.voiceInstance, (VE_PARAM_PITCH, pitch)))

	def _getAvailableVoices(self):
		voices = []
		for items in self._resources.values():
			voices.extend(items)
		return OrderedDict([(v.id, v) for v in voices])

	def _get_voice(self):
		return self._voice

	def _set_voice(self, voice):
		if voice == self.voice: return
		if voice not in self.availableVoices:
			raise RuntimeError("Unavailable voice: %s" % voice)
		self._voice = voice
		# Available variants are cached by default. As variants maybe different for each voice remove the cached value
		if hasattr(self, "_availableVariants"):
			del self._availableVariants

	def _get_variant(self):
		return self.getParameter(self.voiceInstance, VE_PARAM_VOICE_OPERATING_POINT, type_=str)

	def _set_variant(self, variant):
		if variant == self.variant: return
		if variant not in self.availableVariants:
			log.warning("Unavailable variant: %s" % variant)
			return
		self._bgQueue.put(TtsSetParamList(self.voiceInstance, (VE_PARAM_VOICE_OPERATING_POINT, variant)))

	def _getAvailableVariants(self):
		language = self.getParameter(self.voiceInstance, VE_PARAM_LANGUAGE, type_=str) # FIXME: store language...
		dbs = ve2.getSpeechDBList(language, self.voice)
		return OrderedDict([(d, VoiceInfo(d, d)) for d in dbs])

	def _get_waitfactor(self):
		return str(self.getParameter(self.voiceInstance, VE_PARAM_WAITFACTOR))

	def _set_waitfactor(self, value):
		self._bgQueue.put(TtsSetParamList(self.voiceInstance, (VE_PARAM_WAITFACTOR, int(value))))

	def _get_availableWaitfactors(self):
		return OrderedDict([(v, VoiceInfo(v, v)) for v in [str(v) for v in range(WAITFACTOR_MIN, WAITFACTOR_MAX+1)]])

	def _get_language(self):
		return self.availableVoices[self.voice].language

	def _get_availableNormalizations(self):
		values = OrderedDict([("OFF", StringParameterInfo("OFF", _("OFF")))])
		for form in ("NFC", "NFKC", "NFD", "NFKD"):
			values[form] = StringParameterInfo(form, form)
		return values

	def _get_normalization(self):
		return self._normalization

	def _set_normalization(self, value):
		if value in self.availableNormalizations:
			self._normalization = value
