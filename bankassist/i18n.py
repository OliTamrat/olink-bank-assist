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
        "did_you_mean": (
            "I want to be sure I understood you correctly. "
            "Were you asking about one of these?"
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
        "did_you_mean": (
            "በትክክል መረዳቴን ማረጋገጥ እፈልጋለሁ። "
            "ከእነዚህ ውስጥ ስለ አንዱ እየጠየቁ ነበር?"
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
        "did_you_mean": (
            "Sirriitti isin hubadhuu mirkaneeffachuun barbaada. "
            "Kanneen keessaa isa tokko gaafachaa turtanii?"
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
        "did_you_mean": (
            "ብልክዕ ከም ዝተረዳእኩኹም ከረጋግጽ እደሊ። "
            "ካብዞም ሓደ ትሓቱ ነይርኩም?"
        ),
        "account_help": (
            "ንድሕነትኩም፣ ኣብዚ ዝርርብ ናይ ውልቂ ሕሳብ ሓበሬታ ክርኢ ኣይክእልን። "
            "በጃኹም ናይ ሞባይል ባንኪ መተግበሪ ተጠቐሙ፣ ጨንፈር ብጽሑ ወይ ንኣገልግሎት ዓማዊል ርኸቡ።"
        ),
        "complaint_ack": (
            "ብዘጋጠመኩም ጸገም ይቕሬታ ንሓትት። መልእኽትኹም ናብ ጉጅለ ኣገልግሎት ዓማዊል "
            "ኣመሓላሊፈዮ ኣለኹ — ሓደ ሰብ ኣብ ቀረባ ግዜ ክረኽበኩም እዩ።"
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
        "did_you_mean": (
            "Waxaan doonayaa inaan hubiyo inaan si sax ah u fahmay. "
            "Ma waxaad wax ka weydiinaysay mid ka mid ah kuwan?"
        ),
        "account_help": (
            "Amnigaaga awgiis, wadahadalkan kuma eegi karo macluumaadka xisaabta gaarka ah. "
            "Fadlan isticmaal abka bangiga mobilada, booqo laan ama la xiriir adeegga macaamiisha."
        ),
        "complaint_ack": (
            "Waan ka xunnahay dhibaatada kaa soo gaartay. Fariintaada waxaan u gudbiyey "
            "kooxda adeegga macaamiisha — qof ayaa dhawaan kula soo xiriiri doona."
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
