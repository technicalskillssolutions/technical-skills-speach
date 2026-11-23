# Technical Skills Speech

यह एक unified NVDA Synthesizer है। इसमें Eloquence और Vocalizer Expressive 2 के लिए अलग-अलग internal backends हैं। NVDA की Synthesizer सूची में केवल Technical Skills Speech दिखाई देगा।

## प्रमुख सुविधाएँ

- Built-in offline Unicode-script language detection.
- Hindi Devanagari text के लिए Vocalizer Neel voice, उपलब्ध होने पर.
- English/Latin text के लिए Eloquence, उपलब्ध होने पर.
- अन्य भाषाओं के लिए उपलब्ध Vocalizer या Eloquence voice का चयन.
- सभी उपलब्ध Eloquence language voices.
- Eloquence के आठ variants: Reed, Shelly, Bobby, Rocko, Glen, Sandy, Grandma और Grandpa.
- हर voice के लिए अलग Rate, Pitch और Volume profiles.
- Eloquence Inflection control.
- Mixed-script segments के लिए serialized speech queue.
- एक ही NVDA Add-on installer.

## स्थापना

एकल `TechnicalSkillsSpeech.nvda-addon` फाइल इंस्टॉल करें। NVDA के restart के बाद NVDA Settings > Speech > Synthesizer में Technical Skills Speech चुनें। Voice setting में Automatic language detection default है।

## Detection की सीमाएँ

यह script-based detection है, पूर्ण semantic language identification नहीं। Romanized Hindi को हमेशा English से अलग पहचानना संभव नहीं है। ऐसे text के लिए NVDA का explicit language metadata अधिक विश्वसनीय है।

## Testing स्थिति

Python files की syntax compilation और package structure validation की गई है। इस build environment में Windows/NVDA runtime उपलब्ध नहीं है, इसलिए इसे अभी पूर्ण runtime-tested या Store-ready stable release नहीं कहा जा सकता। Public release से पहले Windows पर दोनों engines, Neel voice, Say All, index notifications, cancellation, pause/resume और voice settings का परीक्षण आवश्यक है।

विस्तृत जानकारी और third-party attribution के लिए `README.md` और `THIRD_PARTY_NOTICES.md` देखें।


## प्रति-वॉइस सेटिंग्स

Rate, Pitch, Volume, Eloquence Variant और Inflection हर engine/voice के लिए अलग-अलग सुरक्षित होते हैं। Automatic मोड में settings ring उस voice की profile बदलती है जिसे सबसे हाल में route किया गया था। किसी खास voice की settings बदलने के लिए Voice सूची में वह Eloquence/Vocalizer voice चुनें, Rate/Pitch/Volume बदलें और फिर जरूरत हो तो Voice को वापस Automatic कर दें। profiles NVDA configuration में सुरक्षित रहती हैं।

## Hindi Neel में छोटे शब्द

Hindi Vocalizer speech में तीन अक्षरों तक के छोटे Devanagari tokens के चारों ओर Vocalizer का `tn=raw` control लगाया जाता है और token के तुरंत बाद `tn=normal` वापस लगाया जाता है। इसका उद्देश्य `रवि`, `मार` और `जन` जैसे छोटे शब्दों को क्रमशः `रविवार`, `March` या `January` के रूप में expand होने से रोकना है। वास्तविक उच्चारण Neel engine के साथ Windows पर जाँचना आवश्यक है।

वेबसाइट: https://technicalskillssolutions.github.io
