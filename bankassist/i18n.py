"""Fixed assistant strings in the five supported languages.

EN and AM have been reviewed with care; OM, TI and SO are first-pass drafts and
must go through the linguist review workflow (same TSV process as Onekof)
before a real bank pilot.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ["en", "am", "om", "ti", "so"]

LANGUAGE_NAMES = {
    "en": "English",
    "am": "አማርኛ",
    "om": "Afaan Oromoo",
    "ti": "ትግርኛ",
    "so": "Soomaali",
}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "greeting": (
            "Hello! I am {bank}'s virtual assistant. Ask me anything about our "
            "accounts, services, fees, or how to bank with us."
        ),
        "greeting_named": (
            "Hello {name}! I am {bank}'s virtual assistant. Ask me anything about "
            "our accounts, services, fees, or how to bank with us."
        ),
        "ack_named": "Thanks {name} —",
        "unknown": (
            "I don't have verified information about that yet, so I won't guess. "
            "I've noted your question for our customer service team — they can follow up with you."
        ),
        "general_guidance": (
            "General guidance — this is standard banking practice, not {bank}'s own "
            "published information. Please check with {bank} for anything specific "
            "to your account."
        ),
        # A statement, not a question. This used to ask "Were you asking about
        # one of these?" and sat *after* the contact request, so the turn
        # closed by asking something other than the thing we needed answered.
        # Topic chips are an offer to browse; they must never compete with the
        # one question a turn is actually for.
        "related_topics": "In the meantime, these related topics may help:",
        "ask_contact": (
            "So a person from our team can get back to you, may I have your name "
            "and the best phone number to reach you on?"
        ),
        "contact_saved": (
            "Thank you — I've passed your details to our customer service team. "
            "They will contact you on {contact}."
        ),
        "contact_saved_named": (
            "Thank you {name} — I've passed your details to our customer service "
            "team. They will contact you on {contact}."
        ),
        "account_help": (
            "For your security, I can't access individual account details in this chat. "
            "Please use the mobile banking app, visit a branch, or contact customer care. "
            "Is there anything general I can help you with?"
        ),
        "complaint_ack": (
            "I'm sorry you've had this experience. I've flagged your message for our "
            "customer service team so a person can follow up with you."
        ),
        # Someone asking for a person is not asking a question. This reached
        # production answering "I don't have verified information about that
        # yet, so I won't guess" to "I need to speak to the manager on site".
        "human_request_ack": (
            "Of course — I've passed you to our customer service team so a person "
            "can help you directly."
        ),
        "advice_disclaimer": (
            "Note: this is general financial education, not personal investment advice. "
            "Please speak with a licensed advisor before making investment decisions."
        ),
        "fallback_intro": "Here is what I found in {bank}'s official information:",
        "sources_label": "Sources",
        "comparison_intro": (
            "I can't make claims about other banks, but here's what makes "
            "{bank} strong:"
        ),
        "comparison_fallback": (
            "I can't compare specific banks, but I'd be glad to tell you "
            "about {bank}'s accounts, services, and features — what would "
            "you like to know?"
        ),
    },
    "am": {
        "greeting": (
            "ሰላም! እኔ የ{bank} ዲጂታል ረዳት ነኝ። ስለ ሂሳቦቻችን፣ አገልግሎቶቻችን፣ "
            "ክፍያዎች ወይም አጠቃቀም ማንኛውንም ጥያቄ ይጠይቁኝ።"
        ),
        "greeting_named": (
            "ሰላም {name}! እኔ የ{bank} ዲጂታል ረዳት ነኝ። ስለ ሂሳቦቻችን፣ አገልግሎቶቻችን፣ "
            "ክፍያዎች ወይም አጠቃቀም ማንኛውንም ጥያቄ ይጠይቁኝ።"
        ),
        "ack_named": "አመሰግናለሁ {name} —",
        "unknown": (
            "ስለዚህ ጉዳይ የተረጋገጠ መረጃ ስለሌለኝ መገመት አልፈልግም። "
            "ጥያቄዎን ለደንበኞች አገልግሎት ቡድናችን አስተላልፌዋለሁ — በቅርቡ ያገኙዎታል።"
        ),
        "general_guidance": (
            "አጠቃላይ መመሪያ — ይህ የተለመደ የባንክ አሠራር እንጂ የ{bank} ይፋዊ መረጃ አይደለም። "
            "ከሂሳብዎ ጋር ለተያያዘ ማንኛውም ጉዳይ {bank}ን ያማክሩ።"
        ),
        "related_topics": "እስከዚያው ድረስ፣ እነዚህ ተዛማጅ ርዕሶች ሊረዱዎት ይችላሉ፦",
        "ask_contact": (
            "ከቡድናችን አንድ ሰው እንዲያገኝዎት፣ ስምዎን እና የሚደረስብዎትን የስልክ ቁጥር "
            "ሊነግሩኝ ይችላሉ?"
        ),
        "contact_saved": (
            "አመሰግናለሁ — መረጃዎን ለደንበኞች አገልግሎት ቡድናችን አስተላልፌያለሁ። "
            "በ{contact} ያገኙዎታል።"
        ),
        "contact_saved_named": (
            "አመሰግናለሁ {name} — መረጃዎን ለደንበኞች አገልግሎት ቡድናችን አስተላልፌያለሁ። "
            "በ{contact} ያገኙዎታል።"
        ),
        "account_help": (
            "ለደህንነትዎ ሲባል በዚህ ውይይት ውስጥ የግል ሂሳብ መረጃ ማየት አልችልም። "
            "እባክዎ የሞባይል ባንኪንግ መተግበሪያውን ይጠቀሙ፣ ቅርንጫፍ ይጎብኙ ወይም "
            "የደንበኞች አገልግሎት ያነጋግሩ። በአጠቃላይ ጉዳይ ልርዳዎት?"
        ),
        "complaint_ack": (
            "ስለደረሰብዎት ችግር ይቅርታ እንጠይቃለን። መልዕክትዎን ለደንበኞች አገልግሎት "
            "ቡድናችን አስተላልፌዋለሁ — አንድ ሰው በቅርቡ ያገኙዎታል።"
        ),
        "human_request_ack": (
            "እሺ — ወደ ደንበኞች አገልግሎት ቡድናችን አስተላልፌዎታለሁ፤ አንድ ሰው በቀጥታ "
            "ያግዝዎታል።"
        ),
        "advice_disclaimer": (
            "ማሳሰቢያ፡ ይህ አጠቃላይ የፋይናንስ ትምህርት እንጂ የግል የኢንቨስትመንት ምክር አይደለም። "
            "ውሳኔ ከማድረግዎ በፊት ፈቃድ ያለው አማካሪ ያማክሩ።"
        ),
        "fallback_intro": "ከ{bank} ይፋዊ መረጃ ያገኘሁት ይህ ነው፡",
        "sources_label": "ምንጮች",
        "comparison_intro": (
            "ስለ ሌሎች ባንኮች መግለጫ መስጠት አልችልም፣ ነገር ግን {bank}ን ጠንካራ "
            "የሚያደርገው ይህ ነው፡"
        ),
        "comparison_fallback": (
            "የተለዩ ባንኮችን ማወዳደር አልችልም፣ ነገር ግን ስለ {bank} ሂሳቦች፣ "
            "አገልግሎቶች እና ባህሪያት በደስታ እነግርዎታለሁ — ምን ማወቅ ይፈልጋሉ?"
        ),
    },
    "om": {
        "greeting": (
            "Akkam! Ani gargaaraa dijitaalaa {bank} ti. Waa'ee herregaa, tajaajilaa, "
            "kaffaltii fi fayyadama keenyaa gaaffii kamiyyuu na gaafadhaa."
        ),
        "greeting_named": (
            "Akkam {name}! Ani gargaaraa dijitaalaa {bank} dha. Waa'ee herregaa, "
            "tajaajilaa, kaffaltii yookaan itti fayyadama gaafadhaa."
        ),
        "ack_named": "Galatoomi {name} —",
        "unknown": (
            "Waa'ee kanaa odeeffannoo mirkanaa'e waan hin qabneef tilmaamuu hin barbaadu. "
            "Gaaffii keessan garee tajaajila maamiltootaa keenyaaf dabarseera — "
            "dhiyootti isin qunnamu."
        ),
        "general_guidance": (
            "Qajeelfama waliigalaa — kun hojimaata baankii idilee malee odeeffannoo "
            "ifaa {bank} miti. Waan herrega keessan ilaallatu kamiyyuu {bank} gaafadhaa."
        ),
        "related_topics": (
            "Hanga sanaatti, mata dureewwan walqabatan kunneen isin gargaaruu danda'u:"
        ),
        "ask_contact": (
            "Namni garee keenyaa akka isin qunnamuuf, maqaa keessanii fi "
            "lakkoofsa bilbilaa ittiin isin argannu naaf kennuu dandeessuu?"
        ),
        "contact_saved": (
            "Galatoomaa — odeeffannoo keessan gara garee tajaajila maamiltootaa "
            "keenyaatti dabarseera. Lakkoofsa {contact} irratti isin qunnamu."
        ),
        "contact_saved_named": (
            "Galatoomaa {name} — odeeffannoo keessan gara garee tajaajila "
            "maamiltootaa keenyaatti dabarseera. Lakkoofsa {contact} irratti "
            "isin qunnamu."
        ),
        "account_help": (
            "Nageenya keessaniif, marii kana keessatti odeeffannoo herrega dhuunfaa arguu "
            "hin danda'u. Maaloo appii baankii mobaayilaa fayyadamaa, damee daawwadhaa "
            "yookiin tajaajila maamiltootaa qunnamaa."
        ),
        "complaint_ack": (
            "Rakkoo isin mudateef dhiifama gaafanna. Ergaa keessan garee tajaajila "
            "maamiltootaaf dabarseera — namni tokko dhiyootti isin qunnama."
        ),
        "human_request_ack": (
            "Tole — garee tajaajila maamiltootaa keenyaatti isin dabarseera, "
            "namni tokko kallattiin isin gargaara."
        ),
        "advice_disclaimer": (
            "Hubachiisa: kun barnoota faayinaansii waliigalaa malee gorsa invastimantii "
            "dhuunfaa miti. Murtoo gochuu keessan dura gorsaa hayyama qabu mariisisaa."
        ),
        "fallback_intro": "Odeeffannoo ifaa {bank} irraa kanan argadhe kana:",
        "sources_label": "Maddawwan",
        "comparison_intro": (
            "Waa'ee baankilee biroo ibsa kennuu hin danda'u, garuu wanti "
            "{bank} jabeessu kanaadha:"
        ),
        "comparison_fallback": (
            "Baankilee addaa wal bira qabuu hin danda'u, garuu waa'ee "
            "herregaa, tajaajilaa fi amaloota {bank} gammachuudhaan "
            "isinitti himuu nan barbaada — maal beekuu barbaaddu?"
        ),
    },
    "ti": {
        "greeting": (
            "ሰላም! ኣነ ናይ {bank} ዲጂታላዊ ሓጋዚ እየ። ብዛዕባ ሕሳባትና፣ ኣገልግሎታትና፣ "
            "ክፍሊታት ወይ ኣጠቓቕማ ዝኾነ ሕቶ ሕተቱኒ።"
        ),
        "greeting_named": (
            "ሰላም {name}! ኣነ ናይ {bank} ዲጂታላዊ ሓጋዚ እየ። ብዛዕባ ሕሳባትና፣ ኣገልግሎትና፣ "
            "ክፍሊት ወይ ኣጠቓቕማ ዝኾነ ሕቶ ሕተቱኒ።"
        ),
        "ack_named": "የቐንየለይ {name} —",
        "unknown": (
            "ብዛዕባ እዚ ዝተረጋገጸ ሓበሬታ ስለ ዘይብለይ ክግምት ኣይደልን። "
            "ሕቶኹም ናብ ጉጅለ ኣገልግሎት ዓማዊልና ኣመሓላሊፈዮ ኣለኹ — ኣብ ቀረባ ግዜ ክረኽቡኹም እዮም።"
        ),
        "general_guidance": (
            "ሓፈሻዊ መምርሒ — እዚ ልሙድ ናይ ባንክ ኣሰራርሓ እምበር ወግዓዊ ሓበሬታ {bank} ኣይኮነን። "
            "ምስ ሕሳብኩም ዝተኣሳሰር ዝኾነ ነገር {bank} ሕተቱ።"
        ),
        "related_topics": "ኣብ መንጎኡ፡ እዞም ተዛመድቲ ኣርእስትታት ክሕግዙኹም ይኽእሉ፦",
        "ask_contact": (
            "ሓደ ኣባል ጋንታና ክረኽበኩም ምእንቲ፡ ስምኩምን እትርከቡሉ ቁጽሪ ተሌፎንን "
            "ክትህቡኒ ትኽእሉ ዶ?"
        ),
        "contact_saved": (
            "የቐንየለይ — ሓበሬታኹም ናብ ጋንታ ኣገልግሎት ዓማዊልና ኣመሓላሊፈዮ ኣለኹ። "
            "ብ{contact} ክረኽቡኹም እዮም።"
        ),
        "contact_saved_named": (
            "የቐንየለይ {name} — ሓበሬታኹም ናብ ጋንታ ኣገልግሎት ዓማዊልና ኣመሓላሊፈዮ ኣለኹ። "
            "ብ{contact} ክረኽቡኹም እዮም።"
        ),
        "account_help": (
            "ንድሕነትኩም፣ ኣብዚ ዝርርብ ናይ ውልቂ ሕሳብ ሓበሬታ ክርኢ ኣይክእልን። "
            "በጃኹም ናይ ሞባይል ባንኪ መተግበሪ ተጠቐሙ፣ ጨንፈር ብጽሑ ወይ ንኣገልግሎት ዓማዊል ርኸቡ።"
        ),
        "complaint_ack": (
            "ብዘጋጠመኩም ጸገም ይቕሬታ ንሓትት። መልእኽትኹም ናብ ጉጅለ ኣገልግሎት ዓማዊል "
            "ኣመሓላሊፈዮ ኣለኹ — ሓደ ሰብ ኣብ ቀረባ ግዜ ክረኽበኩም እዩ።"
        ),
        "human_request_ack": (
            "ሕራይ — ናብ ጉጅለ ኣገልግሎት ዓማዊልና ኣመሓላሊፈኩም ኣለኹ፡ ሓደ ሰብ ብቐጥታ "
            "ክሕግዘኩም እዩ።"
        ),
        "advice_disclaimer": (
            "መዘኻኸሪ፡ እዚ ሓፈሻዊ ፋይናንሳዊ ትምህርቲ እምበር ናይ ውልቂ ናይ ኢንቨስትመንት ምኽሪ "
            "ኣይኮነን። ቅድሚ ውሳነ ምግባርኩም ፍቓድ ዘለዎ ኣማኻሪ ተወከሱ።"
        ),
        "fallback_intro": "ካብ ወግዓዊ ሓበሬታ {bank} ዝረኸብክዎ እዚ እዩ፡",
        "sources_label": "ምንጭታት",
        "comparison_intro": (
            "ብዛዕባ ካልኦት ባንክታት መግለጺ ክህብ ኣይክእልን፣ እንተኾነ ን{bank} ብርቱዕ "
            "ዝገብሮ እዚ እዩ፡"
        ),
        "comparison_fallback": (
            "ፍሉያት ባንክታት ከወዳድር ኣይክእልን፣ እንተኾነ ብዛዕባ ናይ {bank} ሕሳባት፣ "
            "ኣገልግሎታትን ባህርያትን ብሓጎስ ክነግረኩም እኽእል እየ — እንታይ ክትፈልጡ ትደልዩ?"
        ),
    },
    "so": {
        "greeting": (
            "Salaan! Waxaan ahay kaaliyaha dijitaalka ah ee {bank}. Wax kasta oo ku "
            "saabsan xisaabaadka, adeegyada, khidmadaha iyo isticmaalka i weydii."
        ),
        "greeting_named": (
            "Salaan {name}! Waxaan ahay kaaliyaha dijitaalka ah ee {bank}. Wax walba "
            "oo ku saabsan xisaabaha, adeegyada, khidmadaha ama isticmaalka i weydii."
        ),
        "ack_named": "Mahadsanid {name} —",
        "unknown": (
            "Arrintan macluumaad la xaqiijiyey kama hayo, mana doonayo inaan qiyaaso. "
            "Su'aashaada waxaan u gudbiyey kooxda adeegga macaamiisha — "
            "dhawaan way kula soo xiriiri doonaan."
        ),
        "general_guidance": (
            "Hagaajin guud — kani waa hab-dhaqanka caadiga ah ee bangiyada, ma aha "
            "macluumaadka rasmiga ah ee {bank}. Wax kasta oo la xiriira xisaabtaada "
            "la xaqiiji {bank}."
        ),
        "related_topics": (
            "Inta u dhaxaysa, mawduucyada la xiriira ee hoos ku qoran "
            "ayaa laga yaabaa inay ku caawiyaan:"
        ),
        "ask_contact": (
            "Si qof ka mid ah kooxdayadu ay kuula soo xiriiraan, ma i siin "
            "kartaa magacaaga iyo lambarka telefoonka ee lagugu heli karo?"
        ),
        "contact_saved": (
            "Mahadsanid — macluumaadkaaga waxaan u gudbiyay kooxda adeegga "
            "macaamiisha. Waxay kugula soo xiriiri doonaan {contact}."
        ),
        "contact_saved_named": (
            "Mahadsanid {name} — macluumaadkaaga waxaan u gudbiyay kooxda "
            "adeegga macaamiisha. Waxay kugula soo xiriiri doonaan {contact}."
        ),
        "account_help": (
            "Amnigaaga awgiis, wadahadalkan kuma eegi karo macluumaadka xisaabta gaarka ah. "
            "Fadlan isticmaal abka bangiga mobilada, booqo laan ama la xiriir adeegga macaamiisha."
        ),
        "complaint_ack": (
            "Waan ka xunnahay dhibaatada kaa soo gaartay. Fariintaada waxaan u gudbiyey "
            "kooxda adeegga macaamiisha — qof ayaa dhawaan kula soo xiriiri doona."
        ),
        "human_request_ack": (
            "Waa hagaag — waxaan kuu gudbiyey kooxda adeegga macaamiisha, "
            "qof ayaa si toos ah kuu caawin doona."
        ),
        "advice_disclaimer": (
            "Ogeysiis: tani waa waxbarasho maaliyadeed oo guud, ma aha talo maalgashi oo "
            "shakhsi ah. Ka hor inta aadan go'aan gaarin, la tasho lataliye shati leh."
        ),
        "fallback_intro": "Waa kan waxa aan ka helay macluumaadka rasmiga ah ee {bank}:",
        "sources_label": "Ilaha",
        "comparison_intro": (
            "Ma bixin karo faallo ku saabsan bangiyada kale, laakiin waa kan "
            "{bank} xoog ka dhigaya:"
        ),
        "comparison_fallback": (
            "Ma barbardhigi karo bangiyo gaar ah, laakiin waan kuu sheegi "
            "lahaa xisaabaadka, adeegyada, iyo astaamaha {bank} — maxaad "
            "rabtaa inaad ogaato?"
        ),
    },
}


def t(language: str | None, key: str, **kwargs: str) -> str:
    lang = language if language in _STRINGS else "en"
    template = _STRINGS[lang].get(key) or _STRINGS["en"][key]
    return template.format(**kwargs) if kwargs else template
