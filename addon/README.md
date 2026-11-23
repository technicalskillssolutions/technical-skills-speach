# Technical Skills Speech

A single NVDA synthesizer integration maintained by Technical Skills Solutions.
It routes speech between Eloquence and Vocalizer Expressive 2, includes the
Hindi Neel EmbeddedCompact voice resource, and performs offline Unicode-script
based language routing.

## Included engines and voices

- All 13 Eloquence `.syn` language voice resources present in the supplied
  Eloquence v27 archive: Chinese, German, English (two variants), Spanish
  (two variants), Finnish, French (two variants), Italian, Japanese, Korean,
  and Brazilian Portuguese.
- Eloquence voice variants: Reed, Shelly, Bobby, Rocko, Glen, Sandy, Grandma,
  and Grandpa.
- Vocalizer Expressive 2 driver and the bundled Hindi Neel voice resource.
- Other Vocalizer voice resources are detected when available through supported
  installed Vocalizer voice packages or supported system voice locations.

## NVDA configuration

Select **Technical Skills Speech** from NVDA's Synthesizer list. The Voice
setting includes:

- **Automatic language detection** (default)
- Individual Eloquence language voices
- Detected Vocalizer voices, including Hindi Neel when its resource initializes

Rate, Pitch, Volume, Eloquence Variant, and Inflection are stored in separate
per-engine/per-voice profiles. Changing one voice does not intentionally
overwrite another voice's settings. In Automatic mode, the settings ring edits
the profile for the most recently routed voice. To edit a particular voice,
select it in the Voice list, change its settings, then return to Automatic when
finished. These profiles persist in NVDA configuration. NVDA per-utterance rate, pitch, and volume commands are
preserved where the selected backend supports them.

## Automatic routing

The driver first respects NVDA `LangChangeCommand` metadata. When no explicit
language metadata is present, it detects Unicode scripts locally and splits
mixed-script text into serialized segments. Hindi Devanagari is routed to the
Vocalizer Hindi voice when available. English/Latin text is routed to Eloquence
when available. Other recognized scripts are routed to a matching Vocalizer
voice when installed, then to a matching Eloquence language voice, with a
fallback to the available default engine.

This is script detection, not full semantic language identification. Latin
transliterations (for example, Romanized Hindi) cannot always be distinguished
from English without explicit language metadata. Han ideographs can also be
ambiguous between Chinese and Japanese without explicit metadata.

## Audio queue and overlap

The unified driver dispatches one segment at a time. It waits for the active
backend's completion callback before sending the next segment. This prevents
both bundled WavePlayers from intentionally speaking at the same time. Exact
latency depends on the native engines, audio device, Windows scheduling, and
voice initialization; zero latency cannot be guaranteed.

## Architecture and compatibility

- One public NVDA SynthDriver: `technicalSkillsSpeech`.
- The Eloquence and Vocalizer backend modules are private modules whose names
  begin with an underscore, so NVDA does not list them as separate synthesizers.
- The bundled Vocalizer resource root is added to the engine resource search.
- Vocalizer selects the DLL directory matching the running NVDA/Python process
  architecture (`AMD64` or `x86`).
- Manifest target: NVDA 2026.1.0 and later; build metadata is set to the latest
  stable release available when this package was assembled (2026.3.1).

## Build

Run `python build_package.py` from the source project root. The script creates
`dist/TechnicalSkillsSpeech.nvda-addon` from the `addon/` directory.

## Important validation status

This source package was statically inspected, the routing/queue logic was
smoke-tested with mocked NVDA/backend interfaces, and Python files were syntax
compiled in the build environment. It has **not** been executed inside Windows
or NVDA in this environment and no native speech output has been verified here.
Before a public stable release, test installation,
NVDA startup, both native engines, all listed Eloquence voices and variants,
Hindi Neel initialization, speech indexes, Say All, cancellation, pause/resume,
configuration persistence, and both process architectures on actual supported
NVDA installations. Do not submit a stable Store release until these runtime
tests pass.

See `THIRD_PARTY_NOTICES.md` and `LICENSES/` for component notices and license
boundaries. The distribution publisher must retain separate written permission
covering the proprietary engine binaries and voice resources.


## Hindi short-word handling

For Hindi Vocalizer speech, Devanagari tokens of up to three letters are scoped with Vocalizer's
`tn=raw` control to block unwanted abbreviation expansion (for example, रवि
being expanded as रविवार, or जन/मार being read as month names). Each token is
immediately returned to normal text-normalization mode so dates and numbers
retain normal processing. Verify pronunciation with the embedded Neel voice
on Windows; actual output depends on the installed Neel engine data.

Website: https://technicalskillssolutions.github.io
