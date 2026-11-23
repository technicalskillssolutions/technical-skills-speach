# Third-party notices and attribution

Technical Skills Speech is the unified NVDA-facing integration maintained by
Technical Skills Solutions. The package bundles and adapts existing speech
engines and resources. Their original notices and licenses are retained in
this distribution wherever supplied by the upstream packages.

## Eloquence v27

- Upstream project: https://github.com/fastfinge/eloquence_64
- The supplied driver source includes the notice `Copyright (C) 2009-2019 eloquence fans`.
- Further modification, packaging, and integration for Technical Skills Speech:
  Technical Skills Solutions, 2026.
- The original `manifest.ini` identified its author field as `NVDA User`; this
  upstream attribution is not silently replaced in the source history.
- Engine resources, ECI components, voice dictionaries, and other embedded
  assets retain their respective upstream rights and notices.

## OpenEVV / ReLoq components bundled with Eloquence

- OpenEVV: copyright and license notices are retained in
  `synthDrivers/openevv/LICENSE` and `synthDrivers/openevv/NOTICE`.
- ReLoq C: notices and license files are retained in
  `synthDrivers/reloq/`.
- OpenCC conversion data: provenance and license are retained in
  `synthDrivers/t2s_data/PROVENANCE.md` and `synthDrivers/t2s_data/LICENSE`.
- Eloquence contour component: notice retained in
  `synthDrivers/contours/LICENSE`.

**Important:** the OpenEVV MIT license does not automatically cover IBM-derived
language data or other proprietary engine assets. The distribution publisher
must retain the separate written authorization covering all bundled engine
and data files.

## Vocalizer Expressive 2 driver

- Original engine technology: Nuance Communications.
- Driver adaptation/modification attribution in the supplied upstream
  documentation: Kvark.
- Further modification, packaging, and integration for Technical Skills Speech:
  Technical Skills Solutions, 2026.
- Upstream community references retained in the supplied documentation include
  https://nvda.ru and https://nvda-addons.ru.
- The upstream driver package supplied for this build did not contain a single
  top-level LICENSE file. Its source/binary redistribution is therefore based
  on the separate permission obtained by the publisher, not on this file being
  an open-source license grant.

## Vocalizer Hindi Neel voice resource

- Voice technology and voice data: Nuance Communications.
- Voice: Neel, Hindi (India), male, adult, EmbeddedCompact.
- Integrated into Technical Skills Speech by Technical Skills Solutions, 2026.
- The supplied voice manifest identifies the original author as Nuance
  Communications INC and references the Russian-speaking NVDA add-on catalog.
- Voice data remains subject to its original rights and the publisher's written
  redistribution permission.

## Redistribution and permission records

The publisher must retain the written permissions authorizing redistribution
of the Nuance driver binaries, Neel voice data, and any IBM-derived Eloquence
assets. Attribution is not a substitute for redistribution authorization.
The permission evidence is intentionally not embedded in this public package.
