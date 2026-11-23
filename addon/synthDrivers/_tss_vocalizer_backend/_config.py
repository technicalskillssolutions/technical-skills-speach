import config
from io import StringIO
from configobj import ConfigObj

_configSpec = """[voices]
[[__many__]]
variant = string(default=None)
rate = integer(default=130,min=50,max=400)
pitch = integer(default=95,min=50,max=200)
volume = integer(default=70,min=0,max=100)
waitfactor = integer(default=1,min=0,max=9)

[autoLanguageSwitching]
useUnicodeLanguageDetection = boolean(default=false)
ignoreNumbersInLanguageDetection = boolean(default=false)
ignorePunctuationInLanguageDetection = boolean(default=true)
latinCharactersLanguage = string(default=en)
CJKCharactersLanguage = string(default=ja)

[[__many__]]
voice = string(default=None)
"""

class VEConfig(object):

	def __init__(self):
		if not config.conf["speech"].isSet("vocalizer_expressive2"):
			config.conf["speech"]["vocalizer_expressive2"] = {}
		confspec = ConfigObj(StringIO(_configSpec), list_values=False, encoding="UTF-8")
		config.conf["speech"]["vocalizer_expressive2"].spec.update(confspec)

	def __getitem__(self, key):
		return config.conf["speech"]["vocalizer_expressive2"][key]

	def __setitem__(self, key, value):
		config.conf["speech"]["vocalizer_expressive2"][key] = value

vocalizerConfig = VEConfig()
