"""
discovery_seed.py — Exhaustive seed data for multi-tier gig/remote work discovery.

Categories cover every type of online contract/freelance/task work EXCLUDING
traditional employment (engineer, accountant, etc. as full-time employees).

Structure per category:
  id            — machine key
  name          — display name
  keywords      — search terms for job boards, Serper, Reddit
  platforms     — direct platforms/marketplaces to scrape
  ats_slugs     — known Greenhouse/Lever company slugs that post these roles
  job_boards    — general boards to search with category keywords
  reddit_subs   — subreddits where these opportunities are discussed/posted
  pay_tier      — "high" $15+/hr equiv, "mid" $5-15, "low" <$5
  notes         — discovery / application notes
"""

CATEGORIES = [

    # ──────────────────────────────────────────────────────────────────────────
    # 1. AI TRAINING & RLHF
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "ai_training",
        "name": "AI Training & RLHF",
        "pay_tier": "high",
        "keywords": [
            "AI trainer", "RLHF", "reinforcement learning human feedback",
            "AI reviewer", "prompt engineer freelance", "model evaluator",
            "LLM evaluator", "AI feedback", "conversation rater",
            "AI response reviewer", "red teaming freelance",
            "alignment researcher contract", "human feedback specialist",
        ],
        "platforms": [
            {"name": "Outlier.ai",          "url": "https://outlier.ai/contributors",         "scrape": "direct"},
            {"name": "Scale AI",            "url": "https://scale.com/jobs",                  "scrape": "greenhouse", "slug": "scaleai"},
            {"name": "DataAnnotation.tech", "url": "https://www.dataannotation.tech/",        "scrape": "direct"},
            {"name": "Toloka",              "url": "https://toloka.ai/",                      "scrape": "greenhouse", "slug": "toloka"},
            {"name": "Surge AI",            "url": "https://www.surgehq.ai/",                 "scrape": "direct"},
            {"name": "Alignerr",            "url": "https://www.alignerr.com/",               "scrape": "direct"},
            {"name": "Cohere",              "url": "https://jobs.ashbyhq.com/cohere",         "scrape": "ashby"},
            {"name": "Imbue",               "url": "https://imbue.com/careers/",              "scrape": "lever"},
            {"name": "Labelbox",            "url": "https://labelbox.com/careers/",           "scrape": "lever", "slug": "labelbox"},
            {"name": "Defined.ai",          "url": "https://www.defined.ai/",                 "scrape": "direct"},
            {"name": "Hive (thehive.ai)",   "url": "https://thehive.ai/",                    "scrape": "direct"},
            {"name": "Sama",                "url": "https://www.sama.com/careers/",           "scrape": "greenhouse", "slug": "sama"},
            {"name": "Cogito Tech",         "url": "https://www.cogitotech.com/",             "scrape": "direct"},
            {"name": "Maxbrain AI",         "url": "https://maxbrainai.com/",                 "scrape": "direct"},
            {"name": "Keylabs.ai",          "url": "https://keylabs.ai/",                     "scrape": "direct"},
            {"name": "TagX",                "url": "https://www.tagx.com/",                   "scrape": "direct"},
            {"name": "AI Perfect Master",   "url": "https://aiperfectmaster.com/",            "scrape": "direct"},
            {"name": "Centific",            "url": "https://www.centific.com/",               "scrape": "greenhouse", "slug": "centific"},
            {"name": "Linarc (Alignerr)",   "url": "https://linarc.com/",                    "scrape": "direct"},
            {"name": "Prolific",            "url": "https://prolific.com/",                   "scrape": "direct"},
            {"name": "Anthropic",           "url": "https://anthropic.com/jobs",              "scrape": "greenhouse", "slug": "anthropic"},
            {"name": "OpenAI",              "url": "https://openai.com/careers/",             "scrape": "greenhouse", "slug": "openai"},
        ],
        "ats_slugs": ["scaleai", "toloka", "sama", "anthropic", "openai", "centific"],
        "job_boards": ["remoteok", "weworkremotely", "remotive"],
        "reddit_subs": ["r/beermoney", "r/slavelabour", "r/mturk", "r/Upwork", "r/outlier_ai"],
        "notes": "Apply directly on platform. Most require a skills quiz. Profile skills field drives matching.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 2. DATA ANNOTATION & LABELING
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "data_annotation",
        "name": "Data Annotation & Labeling",
        "pay_tier": "mid",
        "keywords": [
            "data annotator", "image annotator", "video annotator",
            "bounding box", "semantic segmentation", "NLP annotation",
            "text labeler", "audio labeler", "object detection labeling",
            "data labeling specialist", "ML data annotation",
            "training data collection", "dataset creator",
        ],
        "platforms": [
            {"name": "Appen",               "url": "https://appen.com/jobs/",                "scrape": "direct"},
            {"name": "Telus International AI","url": "https://www.telusinternational.com/solutions/ai-data", "scrape": "greenhouse", "slug": "telusinternational"},
            {"name": "Remotasks",           "url": "https://www.remotasks.com/",             "scrape": "direct"},
            {"name": "Clickworker",         "url": "https://www.clickworker.com/",           "scrape": "direct"},
            {"name": "iMerit",              "url": "https://imerit.net/",                    "scrape": "direct"},
            {"name": "CloudFactory",        "url": "https://www.cloudfactory.com/",          "scrape": "direct"},
            {"name": "Spare5 (Appen)",      "url": "https://spare5.com/",                   "scrape": "direct"},
            {"name": "Lionbridge AI",       "url": "https://lionbridge.com/ai-data-services/","scrape": "direct"},
            {"name": "TaskUs",              "url": "https://www.taskus.com/careers/",        "scrape": "greenhouse", "slug": "taskus"},
            {"name": "Playment",            "url": "https://playment.io/",                   "scrape": "direct"},
            {"name": "Deep Vision Data",    "url": "https://deepvisiondata.com/",            "scrape": "direct"},
            {"name": "Alegion",             "url": "https://www.alegion.com/",               "scrape": "direct"},
            {"name": "iSoftStone",          "url": "https://www.isoftstone.com/",            "scrape": "direct"},
            {"name": "Microworkers",        "url": "https://microworkers.com/",              "scrape": "direct"},
            {"name": "Picoworkers",         "url": "https://picoworkers.com/",               "scrape": "direct"},
        ],
        "ats_slugs": ["telusinternational", "taskus"],
        "job_boards": ["remoteok", "indeed", "linkedin"],
        "reddit_subs": ["r/beermoney", "r/mturk", "r/WorkOnline"],
        "notes": "Account registration flow. Many pay per task/hour. Appen and Telus are most consistent.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 3. SEARCH QUALITY RATING & WEB EVALUATION
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "search_rating",
        "name": "Search Quality Rating & Web Evaluation",
        "pay_tier": "mid",
        "keywords": [
            "search quality rater", "search evaluator", "internet assessor",
            "web evaluator", "ads quality rater", "maps quality",
            "relevance rater", "online search evaluation",
            "UQRH", "EEAT evaluator", "search result rater",
        ],
        "platforms": [
            {"name": "Telus International (RaterLabs)", "url": "https://www.raterlabs.com/", "scrape": "direct"},
            {"name": "Appen",               "url": "https://appen.com/jobs/",                "scrape": "direct"},
            {"name": "Lionbridge",          "url": "https://lionbridge.com/",                "scrape": "direct"},
            {"name": "iSoftStone",          "url": "https://www.isoftstone.com/",            "scrape": "direct"},
        ],
        "ats_slugs": ["telusinternational"],
        "job_boards": ["indeed", "glassdoor"],
        "reddit_subs": ["r/search_quality_evaluator", "r/WorkOnline", "r/beermoney"],
        "notes": "Google / Bing use these vendors. Requires passing exam. $12-18/hr. Long-term stable.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 4. TRANSCRIPTION & CAPTIONING
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "transcription",
        "name": "Transcription & Captioning",
        "pay_tier": "mid",
        "keywords": [
            "transcriptionist", "transcription freelance", "audio typist",
            "captioner", "subtitler", "closed captions", "live captioning",
            "medical transcription", "legal transcription", "general transcription",
            "video captioning", "subtitle creator", "voice to text",
        ],
        "platforms": [
            {"name": "Rev",             "url": "https://www.rev.com/freelancers",        "scrape": "direct"},
            {"name": "TranscribeMe",    "url": "https://www.transcribeme.com/jobs",      "scrape": "direct"},
            {"name": "GoTranscript",    "url": "https://gotranscript.com/transcription-jobs", "scrape": "direct"},
            {"name": "Scribie",         "url": "https://scribie.com/freelance-transcription", "scrape": "direct"},
            {"name": "GMR Transcription","url": "https://www.gmrtranscription.com/",    "scrape": "direct"},
            {"name": "Speechpad",       "url": "https://www.speechpad.com/",            "scrape": "direct"},
            {"name": "CastingWords",    "url": "https://castingwords.com/",             "scrape": "direct"},
            {"name": "Daily Transcription","url": "https://www.dailytranscription.com/","scrape": "direct"},
            {"name": "Net Transcripts", "url": "https://www.nettranscripts.com/",       "scrape": "direct"},
            {"name": "3Play Media",     "url": "https://www.3playmedia.com/",           "scrape": "direct"},
            {"name": "Verbit",          "url": "https://verbit.ai/",                   "scrape": "greenhouse", "slug": "verbit"},
            {"name": "Caption.Ed",      "url": "https://caption.ed/",                  "scrape": "direct"},
            {"name": "Acutranscribe",   "url": "https://acutranscribe.com/",           "scrape": "direct"},
        ],
        "ats_slugs": ["verbit"],
        "job_boards": ["indeed", "problogger"],
        "reddit_subs": ["r/Transcription", "r/WorkOnline", "r/beermoney"],
        "notes": "Rev and TranscribeMe are best entry points. Skills test required. Pay per audio minute.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 5. TRANSLATION & LOCALIZATION
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "translation",
        "name": "Translation & Localization",
        "pay_tier": "mid",
        "keywords": [
            "translator freelance", "localization specialist", "language specialist",
            "bilingual freelance", "native speaker", "subtitle translator",
            "document translator", "software localization", "game localization",
            "post-editing machine translation", "MTPE", "linguistic quality",
            "interpreting remote", "sworn translator",
        ],
        "platforms": [
            {"name": "Gengo",               "url": "https://gengo.com/translators/",      "scrape": "direct"},
            {"name": "ProZ",                "url": "https://www.proz.com/translator-jobs/","scrape": "direct"},
            {"name": "One Hour Translation","url": "https://www.onehourtranslation.com/", "scrape": "direct"},
            {"name": "Translated.net",      "url": "https://translated.com/",            "scrape": "direct"},
            {"name": "Lionbridge",          "url": "https://lionbridge.com/",            "scrape": "direct"},
            {"name": "Welocalize",          "url": "https://www.welocalize.com/",        "scrape": "greenhouse", "slug": "welocalize"},
            {"name": "RWS Group",           "url": "https://www.rws.com/careers/",       "scrape": "greenhouse", "slug": "rwsgroup"},
            {"name": "TranslatorsCafe",     "url": "https://www.translatorscafe.com/",  "scrape": "direct"},
            {"name": "Unbabel",             "url": "https://unbabel.com/",              "scrape": "greenhouse", "slug": "unbabel"},
            {"name": "Textmaster",          "url": "https://eu.textmaster.com/",        "scrape": "direct"},
            {"name": "Acclaro",             "url": "https://www.acclaro.com/",          "scrape": "direct"},
            {"name": "Appen",               "url": "https://appen.com/jobs/",           "scrape": "direct"},
            {"name": "Defined.ai",          "url": "https://www.defined.ai/",           "scrape": "direct"},
        ],
        "ats_slugs": ["welocalize", "rwsgroup", "unbabel"],
        "job_boards": ["proz", "translatorscafe", "remotely"],
        "reddit_subs": ["r/TranslationStudies", "r/freelance", "r/WorkOnline"],
        "notes": "English + one other language minimum. Swahili + English is underserved and high-demand.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 6. CONTENT WRITING & COPYWRITING
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "content_writing",
        "name": "Content Writing & Copywriting",
        "pay_tier": "mid",
        "keywords": [
            "content writer freelance", "copywriter remote", "blog writer",
            "SEO content writer", "article writer", "ghostwriter",
            "technical writer freelance", "product description writer",
            "UX writer", "email copywriter", "social media writer",
            "newsletter writer", "scriptwriter freelance", "grant writer",
        ],
        "platforms": [
            {"name": "Textbroker",      "url": "https://www.textbroker.com/",           "scrape": "direct"},
            {"name": "iWriter",         "url": "https://www.iwriter.com/",              "scrape": "direct"},
            {"name": "WriterAccess",    "url": "https://www.writeraccess.com/",         "scrape": "direct"},
            {"name": "Crowd Content",   "url": "https://www.crowdcontent.com/",         "scrape": "direct"},
            {"name": "Verblio",         "url": "https://www.verblio.com/",              "scrape": "direct"},
            {"name": "Scripted",        "url": "https://www.scripted.com/",             "scrape": "direct"},
            {"name": "ContentFly",      "url": "https://contentfly.com/",              "scrape": "direct"},
            {"name": "ClearVoice",      "url": "https://www.clearvoice.com/",          "scrape": "direct"},
            {"name": "Constant Content","url": "https://www.constant-content.com/",    "scrape": "direct"},
            {"name": "Compose.ly",      "url": "https://www.compose.ly/",              "scrape": "direct"},
            {"name": "WordAgents",      "url": "https://wordagents.com/",              "scrape": "direct"},
            {"name": "Skyword",         "url": "https://www.skyword.com/",             "scrape": "direct"},
            {"name": "Contently",       "url": "https://contently.com/",              "scrape": "direct"},
            {"name": "Express Writers", "url": "https://expresswriters.com/",         "scrape": "direct"},
            {"name": "Brafton",         "url": "https://www.brafton.com/",            "scrape": "greenhouse", "slug": "brafton"},
            {"name": "WordStream (LOCALiQ)","url": "https://localiq.com/careers/",    "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["problogger", "bloggingpro", "journalismjobs", "remoteok", "mediabistro"],
        "reddit_subs": ["r/freelanceWriters", "r/writing", "r/Upwork", "r/copywriting"],
        "notes": "Textbroker and iWriter for beginners. Pay scales with star rating. Portfolio accelerates income.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 7. VIRTUAL ASSISTANT & ADMIN SUPPORT
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "virtual_assistant",
        "name": "Virtual Assistant & Admin Support",
        "pay_tier": "mid",
        "keywords": [
            "virtual assistant", "VA remote", "administrative assistant remote",
            "executive virtual assistant", "personal assistant remote",
            "data entry remote", "online research assistant",
            "email management", "calendar management", "scheduling assistant",
            "inbox manager", "CRM data entry", "e-commerce assistant",
            "Amazon seller VA", "Shopify VA",
        ],
        "platforms": [
            {"name": "Belay Solutions",     "url": "https://belaysolutions.com/",        "scrape": "direct"},
            {"name": "Time Etc",            "url": "https://web.timeetc.com/",           "scrape": "direct"},
            {"name": "Fancy Hands",         "url": "https://fancyhands.com/",            "scrape": "direct"},
            {"name": "Zirtual",             "url": "https://www.zirtual.com/",           "scrape": "direct"},
            {"name": "Boldly",              "url": "https://boldly.com/",                "scrape": "direct"},
            {"name": "Magic (getmagic.com)","url": "https://getmagic.com/",             "scrape": "direct"},
            {"name": "Equivity",            "url": "https://www.equivity.com/",          "scrape": "direct"},
            {"name": "24/7 Virtual Assistant","url": "https://www.24task.com/",         "scrape": "direct"},
            {"name": "MyTasker",            "url": "https://www.mytasker.com/",          "scrape": "direct"},
            {"name": "GetFriday",           "url": "https://www.getfriday.com/",         "scrape": "direct"},
            {"name": "Wishup",              "url": "https://www.wishup.co/",             "scrape": "direct"},
            {"name": "TaskBullet",          "url": "https://www.taskbullet.com/",        "scrape": "direct"},
            {"name": "Delegated",           "url": "https://www.delegated.com/",         "scrape": "direct"},
            {"name": "Virtual Latinos",     "url": "https://virtuallatinos.com/",        "scrape": "direct"},
            {"name": "Hello Rache (Medical VA)","url": "https://hellorache.com/",       "scrape": "direct"},
            {"name": "Prialto",             "url": "https://www.prialto.com/",           "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["remoteok", "weworkremotely", "virtualvocations", "flexjobs"],
        "reddit_subs": ["r/VirtualAssistant", "r/WorkOnline", "r/freelance"],
        "notes": "Most require application + interview. Steady $12-25/hr. US timezone often preferred.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 8. CUSTOMER SERVICE & LIVE SUPPORT
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "customer_service",
        "name": "Customer Service & Live Support",
        "pay_tier": "mid",
        "keywords": [
            "remote customer service", "customer support agent remote",
            "live chat agent", "help desk remote", "ticket support",
            "technical support remote", "customer success remote",
            "e-commerce support", "chat support", "email support agent",
            "retention specialist remote", "billing support",
        ],
        "platforms": [
            {"name": "Working Solutions",   "url": "https://www.workingsolutions.com/",   "scrape": "direct"},
            {"name": "LiveOps",             "url": "https://www.liveops.com/",            "scrape": "direct"},
            {"name": "Arise",               "url": "https://www.arise.com/",              "scrape": "direct"},
            {"name": "TTEC Remote",         "url": "https://www.ttecjobs.com/en",         "scrape": "greenhouse", "slug": "ttec"},
            {"name": "Concentrix",          "url": "https://jobs.concentrix.com/",        "scrape": "direct"},
            {"name": "Teleperformance",     "url": "https://jobs.teleperformance.com/",   "scrape": "direct"},
            {"name": "Sykes (Foundever)",   "url": "https://careers.foundever.com/",      "scrape": "direct"},
            {"name": "ibex",                "url": "https://ibex.co/careers/",            "scrape": "direct"},
            {"name": "Helpware",            "url": "https://helpware.com/careers/",       "scrape": "greenhouse", "slug": "helpware"},
            {"name": "Influx",              "url": "https://influx.com/jobs",             "scrape": "direct"},
            {"name": "The Chat Shop",       "url": "https://thechatshop.com/",            "scrape": "direct"},
            {"name": "VIPdesk Connect",     "url": "https://vipdesk.com/",               "scrape": "direct"},
            {"name": "NexRep",              "url": "https://www.nexrep.com/",             "scrape": "direct"},
            {"name": "KellyConnect",        "url": "https://www.kellyservices.com/",      "scrape": "direct"},
            {"name": "Omni Interactions",   "url": "https://www.omniinteractions.com/",   "scrape": "direct"},
            {"name": "ModSquad",            "url": "https://modsquad.com/",              "scrape": "direct"},
        ],
        "ats_slugs": ["ttec", "helpware"],
        "job_boards": ["remoteok", "indeed", "linkedin"],
        "reddit_subs": ["r/remotework", "r/WorkOnline", "r/cscareerquestions"],
        "notes": "TTEC and Concentrix are best for non-US applicants. Often equipment-provided.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 9. CONTENT MODERATION & TRUST AND SAFETY
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "content_moderation",
        "name": "Content Moderation & Trust and Safety",
        "pay_tier": "mid",
        "keywords": [
            "content moderator remote", "trust and safety analyst",
            "policy enforcement remote", "community moderator",
            "social media reviewer", "content reviewer remote",
            "online safety specialist", "UGC reviewer", "hate speech reviewer",
            "misinformation reviewer", "video reviewer", "image reviewer",
        ],
        "platforms": [
            {"name": "ModSquad",            "url": "https://modsquad.com/",              "scrape": "direct"},
            {"name": "Teleperformance",     "url": "https://jobs.teleperformance.com/",  "scrape": "direct"},
            {"name": "Accenture (content)", "url": "https://accenture.com/jobs",         "scrape": "greenhouse", "slug": "accenture"},
            {"name": "TaskUs (T&S)",        "url": "https://www.taskus.com/careers/",    "scrape": "greenhouse", "slug": "taskus"},
            {"name": "Telus International", "url": "https://careers.telusinternational.com/","scrape": "greenhouse", "slug": "telusinternational"},
            {"name": "Crisp Thinking",      "url": "https://www.crispthinking.com/",     "scrape": "direct"},
            {"name": "Arvato",              "url": "https://www.arvato.com/",            "scrape": "direct"},
            {"name": "Cognizant",           "url": "https://careers.cognizant.com/",     "scrape": "greenhouse", "slug": "cognizant"},
        ],
        "ats_slugs": ["taskus", "telusinternational", "cognizant"],
        "job_boards": ["linkedin", "indeed", "remoteok"],
        "reddit_subs": ["r/remotework", "r/WorkOnline"],
        "notes": "High demand post-2020. Often 6-12 month contracts. Mental health support varies by employer.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 10. ONLINE TUTORING & TEACHING
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "online_tutoring",
        "name": "Online Tutoring & Teaching",
        "pay_tier": "high",
        "keywords": [
            "online tutor", "ESL teacher remote", "English teacher online",
            "language tutor", "math tutor remote", "science tutor",
            "test prep tutor", "homework help tutor", "online instructor",
            "academic coach remote", "STEM tutor", "coding tutor",
            "college essay coach", "SAT ACT tutor",
        ],
        "platforms": [
            {"name": "Cambly",          "url": "https://www.cambly.com/en/tutors",        "scrape": "direct"},
            {"name": "iTalki",          "url": "https://www.italki.com/teacher/apply",    "scrape": "direct"},
            {"name": "Preply",          "url": "https://preply.com/en/teach",             "scrape": "direct"},
            {"name": "VIPKid",          "url": "https://www.vipkid.com/teach",            "scrape": "direct"},
            {"name": "Tutor.com",       "url": "https://www.tutor.com/apply",             "scrape": "direct"},
            {"name": "Wyzant",          "url": "https://www.wyzant.com/tutors/apply",     "scrape": "direct"},
            {"name": "Chegg Tutors",    "url": "https://www.chegg.com/tutors/become-a-tutor/","scrape": "direct"},
            {"name": "Varsity Tutors",  "url": "https://www.varsitytutors.com/tutors/apply","scrape": "direct"},
            {"name": "TutorMe",         "url": "https://tutorme.com/tutors/",             "scrape": "direct"},
            {"name": "Outschool",       "url": "https://outschool.com/teach",             "scrape": "direct"},
            {"name": "Magic Ears",      "url": "https://www.magicears.com.cn/",           "scrape": "direct"},
            {"name": "PalFish",         "url": "https://www.palfish.com/",               "scrape": "direct"},
            {"name": "GoGoKid",         "url": "https://www.gogokid.com/teacher.html",   "scrape": "direct"},
            {"name": "QKids",           "url": "https://teacher.qkids.com/",             "scrape": "direct"},
            {"name": "Skooli",          "url": "https://www.skooli.com/",                "scrape": "direct"},
            {"name": "TeachAway",       "url": "https://www.teachaway.com/",             "scrape": "direct"},
            {"name": "Learn To Be",     "url": "https://www.learntobe.org/",             "scrape": "direct"},
            {"name": "Education First", "url": "https://www.ef.com/",                   "scrape": "direct"},
            {"name": "Udemy",           "url": "https://www.udemy.com/teaching/",        "scrape": "direct"},
            {"name": "Skillshare",      "url": "https://www.skillshare.com/teach",       "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["linkedin", "indeed", "remoteok"],
        "reddit_subs": ["r/ESL", "r/Tutoring", "r/freelance"],
        "notes": "Cambly lowest barrier (English conversation only). VIPKid highest pay if fluent English.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 11. SOFTWARE TESTING & QA
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "software_testing",
        "name": "Software Testing & QA (Crowdsourced)",
        "pay_tier": "mid",
        "keywords": [
            "software tester freelance", "QA tester remote", "bug hunter",
            "app tester", "game tester remote", "beta tester paid",
            "usability tester", "crowd testing", "exploratory testing",
            "mobile app tester", "regression tester freelance",
        ],
        "platforms": [
            {"name": "uTest",               "url": "https://www.utest.com/",             "scrape": "direct"},
            {"name": "Testbirds",           "url": "https://testbirds.com/",             "scrape": "direct"},
            {"name": "Test.io",             "url": "https://test.io/",                  "scrape": "direct"},
            {"name": "Global App Testing",  "url": "https://www.globalapptesting.com/",  "scrape": "direct"},
            {"name": "Applause",            "url": "https://www.applause.com/",          "scrape": "greenhouse", "slug": "applause"},
            {"name": "Testlio",             "url": "https://testlio.com/",              "scrape": "greenhouse", "slug": "testlio"},
            {"name": "Passbrains",          "url": "https://passbrains.com/",           "scrape": "direct"},
            {"name": "BugFinders",          "url": "https://bugfinders.com/",           "scrape": "direct"},
            {"name": "Crowd Testing",       "url": "https://crowd.testing/",            "scrape": "direct"},
            {"name": "Rainforest QA",       "url": "https://www.rainforestqa.com/",     "scrape": "greenhouse", "slug": "rainforestqa"},
        ],
        "ats_slugs": ["applause", "testlio", "rainforestqa"],
        "job_boards": ["remoteok", "weworkremotely"],
        "reddit_subs": ["r/softwaretesting", "r/QualityAssurance", "r/WorkOnline"],
        "notes": "Pay per bug found. uTest and Applause are most established. Technical skill needed for complex tests.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 12. USER RESEARCH & UX TESTING
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "ux_testing",
        "name": "User Research & UX Testing",
        "pay_tier": "high",
        "keywords": [
            "usability tester", "UX research participant", "user testing paid",
            "website tester", "app feedback", "think aloud study",
            "focus group online", "paid UX research", "UI feedback",
            "product research participant",
        ],
        "platforms": [
            {"name": "UserTesting",     "url": "https://www.usertesting.com/be-a-user-tester", "scrape": "direct"},
            {"name": "TryMyUI",         "url": "https://www.trymyui.com/",               "scrape": "direct"},
            {"name": "Userlytics",      "url": "https://www.userlytics.com/",            "scrape": "direct"},
            {"name": "Playtest Cloud",  "url": "https://playtestcloud.com/",             "scrape": "direct"},
            {"name": "Testbirds",       "url": "https://testbirds.com/",                "scrape": "direct"},
            {"name": "Respondent.io",   "url": "https://www.respondent.io/",            "scrape": "direct"},
            {"name": "Intellizoom",     "url": "https://www.intellizoom.com/",          "scrape": "direct"},
            {"name": "Maze",            "url": "https://maze.co/",                      "scrape": "direct"},
            {"name": "Loop11",          "url": "https://www.loop11.com/",              "scrape": "direct"},
            {"name": "Validately",      "url": "https://validately.com/",              "scrape": "direct"},
            {"name": "WhatUsersDo",     "url": "https://www.whatusersdo.com/",         "scrape": "direct"},
            {"name": "Enroll (PingPong)","url": "https://www.pingpong.com/",           "scrape": "direct"},
            {"name": "Userfeel",        "url": "https://www.userfeel.com/",            "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": [],
        "reddit_subs": ["r/beermoney", "r/WorkOnline", "r/UXResearch"],
        "notes": "$10-65 per session. UserTesting highest volume. Respondent.io highest pay ($100+ for professionals).",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 13. ACADEMIC & SURVEY RESEARCH
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "surveys_research",
        "name": "Academic & Survey Research",
        "pay_tier": "low",
        "keywords": [
            "paid survey", "research participant", "academic study paid",
            "online survey paid", "panel survey", "market research survey",
            "consumer panel", "focus group paid",
        ],
        "platforms": [
            {"name": "Prolific",        "url": "https://prolific.com/",                "scrape": "direct"},
            {"name": "Respondent.io",   "url": "https://www.respondent.io/",           "scrape": "direct"},
            {"name": "Survey Junkie",   "url": "https://www.surveyjunkie.com/",        "scrape": "direct"},
            {"name": "Swagbucks",       "url": "https://www.swagbucks.com/",           "scrape": "direct"},
            {"name": "InboxDollars",    "url": "https://www.inboxdollars.com/",        "scrape": "direct"},
            {"name": "Pinecone Research","url": "https://www.pineconeresearch.com/",   "scrape": "direct"},
            {"name": "Vindale Research","url": "https://www.vindale.com/",            "scrape": "direct"},
            {"name": "Panel Station",   "url": "https://www.thepanelstation.com/",    "scrape": "direct"},
            {"name": "YouGov",          "url": "https://yougov.co.uk/",              "scrape": "direct"},
            {"name": "Ipsos iSay",      "url": "https://www.ipsosisay.com/",         "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": [],
        "reddit_subs": ["r/beermoney", "r/paidsurveys"],
        "notes": "Prolific is highest quality/pay. Most are supplementary income only. Not worth applying en masse.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 14. VOICE ACTING & AUDIO WORK
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "voice_audio",
        "name": "Voice Acting & Audio Work",
        "pay_tier": "high",
        "keywords": [
            "voice actor remote", "voice over freelance", "narrator remote",
            "audiobook narrator", "podcast editor", "audio description",
            "IVR voice talent", "explainer video voice", "commercial voice",
            "character voice", "ADR voice", "dubbing",
        ],
        "platforms": [
            {"name": "Voices.com",      "url": "https://www.voices.com/",              "scrape": "direct"},
            {"name": "Voice123",        "url": "https://www.voice123.com/",            "scrape": "direct"},
            {"name": "ACX (Audible)",   "url": "https://www.acx.com/",                "scrape": "direct"},
            {"name": "Voice Bunny",     "url": "https://voicebunny.com/",             "scrape": "direct"},
            {"name": "Voice Realm",     "url": "https://www.thevoicerealm.com/",      "scrape": "direct"},
            {"name": "Backstage",       "url": "https://www.backstage.com/",          "scrape": "direct"},
            {"name": "Casting Call Club","url": "https://www.castingcall.club/",      "scrape": "direct"},
            {"name": "Snap Recordings", "url": "https://www.snaprecordings.com/",     "scrape": "direct"},
            {"name": "Voquent",         "url": "https://voquent.com/",               "scrape": "direct"},
            {"name": "Bodalgo",         "url": "https://www.bodalgo.com/",           "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["castingcallclub", "backstage"],
        "reddit_subs": ["r/VoiceActing", "r/audioengineering"],
        "notes": "Requires good mic + quiet space. Audition-based. Can earn $100-500/hr once established.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 15. GRAPHIC DESIGN & CREATIVE SERVICES
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "design_creative",
        "name": "Graphic Design & Creative Services",
        "pay_tier": "mid",
        "keywords": [
            "graphic designer freelance", "logo designer remote",
            "UI designer freelance", "UX designer contract",
            "illustrator freelance", "video editor remote",
            "motion graphics freelance", "social media designer",
            "brand identity designer", "infographic designer",
            "photo editor remote", "photo retoucher",
        ],
        "platforms": [
            {"name": "99designs",       "url": "https://99designs.com/designers",       "scrape": "direct"},
            {"name": "DesignCrowd",     "url": "https://www.designcrowd.com/designers", "scrape": "direct"},
            {"name": "Dribbble Jobs",   "url": "https://dribbble.com/jobs",             "scrape": "direct"},
            {"name": "Behance Jobs",    "url": "https://www.behance.net/joblist",       "scrape": "direct"},
            {"name": "Toptal Design",   "url": "https://www.toptal.com/designers",      "scrape": "direct"},
            {"name": "PeoplePerHour",   "url": "https://www.peopleperhour.com/",        "scrape": "direct"},
            {"name": "Guru",            "url": "https://www.guru.com/",                "scrape": "direct"},
            {"name": "Freelancer.com",  "url": "https://www.freelancer.com/",          "scrape": "direct"},
            {"name": "DesignHill",      "url": "https://www.designhill.com/",          "scrape": "direct"},
            {"name": "Contra",          "url": "https://contra.com/",                  "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["dribbble", "behance", "remoteok"],
        "reddit_subs": ["r/graphic_design", "r/freelance", "r/designjobs"],
        "notes": "Portfolio is mandatory. 99designs contests are open entry. Contra is invite-free and no commission.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 16. ONLINE RESEARCH & INVESTIGATIVE TASKS
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "online_research",
        "name": "Online Research & Investigative Tasks",
        "pay_tier": "mid",
        "keywords": [
            "online researcher", "internet researcher", "market researcher remote",
            "competitive intelligence", "lead generation remote",
            "data collection remote", "web research", "business researcher",
            "LinkedIn researcher", "prospect research",
            "OSINT analyst freelance", "due diligence researcher",
        ],
        "platforms": [
            {"name": "Wonder (AskWonder)","url": "https://askwonder.com/",             "scrape": "direct"},
            {"name": "Techpacker",       "url": "https://techpacker.com/",             "scrape": "direct"},
            {"name": "Fancy Hands",      "url": "https://fancyhands.com/",             "scrape": "direct"},
            {"name": "CloudPeeps",       "url": "https://www.cloudpeeps.com/",         "scrape": "direct"},
            {"name": "Upwork",           "url": "https://www.upwork.com/",             "scrape": "direct"},
            {"name": "Guru",             "url": "https://www.guru.com/",              "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["upwork", "guru", "freelancer"],
        "reddit_subs": ["r/freelance", "r/WorkOnline"],
        "notes": "Wonder is highest quality but competitive. Most research tasks come through VA/freelance platforms.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 17. BOOKKEEPING & FINANCIAL TASKS (NON-EMPLOYEE)
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "bookkeeping_finance",
        "name": "Bookkeeping & Financial Tasks (Freelance)",
        "pay_tier": "high",
        "keywords": [
            "bookkeeper freelance", "virtual bookkeeper",
            "QuickBooks freelance", "Xero bookkeeper remote",
            "accounts payable remote", "accounts receivable freelance",
            "payroll specialist freelance", "tax preparer remote",
            "financial data entry", "invoice processing remote",
        ],
        "platforms": [
            {"name": "Bench",           "url": "https://bench.co/",                   "scrape": "greenhouse", "slug": "benchaccounting"},
            {"name": "Bookkeeper360",   "url": "https://bookkeeper360.com/",          "scrape": "direct"},
            {"name": "Botkeeper",       "url": "https://botkeeper.com/",              "scrape": "greenhouse", "slug": "botkeeper"},
            {"name": "Belay Bookkeeping","url": "https://belaysolutions.com/",        "scrape": "direct"},
            {"name": "QXAS",            "url": "https://www.qxas.com/",              "scrape": "direct"},
            {"name": "BooXkeeping",     "url": "https://www.booXkeeping.com/",       "scrape": "direct"},
            {"name": "Remote Books Online","url": "https://www.remotebooksonline.com/","scrape": "direct"},
            {"name": "Pilot (YC)",      "url": "https://pilot.com/careers",          "scrape": "greenhouse", "slug": "pilot-com"},
        ],
        "ats_slugs": ["benchaccounting", "botkeeper", "pilot-com"],
        "job_boards": ["accountingfly", "remoteok"],
        "reddit_subs": ["r/Bookkeeping", "r/accounting", "r/freelance"],
        "notes": "Requires QuickBooks/Xero certification. High barrier but $20-50/hr. Very stable remote work.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 18. E-COMMERCE & MARKETPLACE SUPPORT
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "ecommerce_support",
        "name": "E-Commerce & Marketplace Support",
        "pay_tier": "mid",
        "keywords": [
            "Amazon FBA virtual assistant", "Shopify store assistant",
            "eBay lister", "product listing specialist", "e-commerce VA",
            "Amazon seller support", "product description writer ecommerce",
            "inventory management remote", "dropshipping assistant",
            "WooCommerce support", "Etsy shop manager",
        ],
        "platforms": [
            {"name": "Amazon (MTurk product)",  "url": "https://www.mturk.com/",          "scrape": "direct"},
            {"name": "Fancy Hands",             "url": "https://fancyhands.com/",         "scrape": "direct"},
            {"name": "VA Staffer",              "url": "https://vastaffer.com/",           "scrape": "direct"},
            {"name": "FreeUp",                  "url": "https://freeup.net/",             "scrape": "direct"},
            {"name": "EcomVA",                  "url": "https://ecomva.com/",             "scrape": "direct"},
            {"name": "Onlinejobs.ph",           "url": "https://www.onlinejobs.ph/",      "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["upwork", "freelancer", "onlinejobsph"],
        "reddit_subs": ["r/FulfillmentByAmazon", "r/shopify", "r/freelance"],
        "notes": "High demand from US/UK Amazon sellers. Onlinejobs.ph is major marketplace but Philippines-focused.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 19. SOCIAL MEDIA MANAGEMENT
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "social_media",
        "name": "Social Media Management & Marketing",
        "pay_tier": "mid",
        "keywords": [
            "social media manager remote", "social media assistant freelance",
            "Instagram manager", "Twitter manager", "TikTok content creator freelance",
            "Facebook ads manager freelance", "community manager remote",
            "influencer outreach", "social media scheduler",
            "LinkedIn content creator", "Pinterest VA",
        ],
        "platforms": [
            {"name": "Socialfly",       "url": "https://socialflyny.com/",             "scrape": "direct"},
            {"name": "SMMExpert Experts","url": "https://www.hootsuite.com/",          "scrape": "direct"},
            {"name": "Upwork",          "url": "https://www.upwork.com/",             "scrape": "direct"},
            {"name": "Contra",          "url": "https://contra.com/",                 "scrape": "direct"},
            {"name": "CloudPeeps",      "url": "https://www.cloudpeeps.com/",         "scrape": "direct"},
            {"name": "Remote.co",       "url": "https://remote.co/",                  "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["remoteok", "weworkremotely"],
        "reddit_subs": ["r/socialmedia", "r/freelance", "r/digital_marketing"],
        "notes": "Portfolio of managed accounts essential. Often bundled with content writing.",
    },

    # ──────────────────────────────────────────────────────────────────────────
    # 20. CODING & TECHNICAL TASKS (FREELANCE/CONTRACT, NOT EMPLOYMENT)
    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "coding_freelance",
        "name": "Coding & Technical Tasks (Freelance/Contract)",
        "pay_tier": "high",
        "keywords": [
            "freelance developer", "contract developer", "bug fix bounty",
            "WordPress developer freelance", "Python freelance",
            "JavaScript freelance", "no-code developer", "automation freelance",
            "Zapier expert", "Make (Integromat) specialist",
            "API integration freelance", "script writing Python",
            "web scraping freelance", "n8n freelance",
        ],
        "platforms": [
            {"name": "Toptal",          "url": "https://www.toptal.com/",              "scrape": "direct"},
            {"name": "Gun.io",          "url": "https://gun.io/",                     "scrape": "direct"},
            {"name": "Lemon.io",        "url": "https://lemon.io/",                  "scrape": "direct"},
            {"name": "Arc.dev",         "url": "https://arc.dev/",                   "scrape": "direct"},
            {"name": "Braintrust",      "url": "https://www.usebraintrust.com/",      "scrape": "direct"},
            {"name": "Contra",          "url": "https://contra.com/",                "scrape": "direct"},
            {"name": "Codementor",      "url": "https://www.codementor.io/",         "scrape": "direct"},
            {"name": "Guru",            "url": "https://www.guru.com/",             "scrape": "direct"},
            {"name": "PeoplePerHour",   "url": "https://www.peopleperhour.com/",    "scrape": "direct"},
            {"name": "X-Team",          "url": "https://x-team.com/",              "scrape": "direct"},
            {"name": "Gigster",         "url": "https://gigster.com/",             "scrape": "direct"},
        ],
        "ats_slugs": [],
        "job_boards": ["remoteok", "weworkremotely", "golangprojects"],
        "reddit_subs": ["r/freelance", "r/learnprogramming", "r/cscareerquestions"],
        "notes": "This is contract/project work only, NOT employment. Python automation, no-code, and API work are high demand.",
    },

]

# ──────────────────────────────────────────────────────────────────────────────
# JOB BOARDS — general boards to search with category keywords
# ──────────────────────────────────────────────────────────────────────────────

JOB_BOARDS = [
    {"id": "remoteok",          "url": "https://remoteok.com/",                    "api": "https://remoteok.com/api",          "type": "json_api"},
    {"id": "weworkremotely",    "url": "https://weworkremotely.com/",              "api": "https://weworkremotely.com/remote-jobs.rss", "type": "rss"},
    {"id": "remotive",          "url": "https://remotive.com/",                    "api": "https://remotive.com/api/remote-jobs", "type": "json_api"},
    {"id": "workingnomads",     "url": "https://www.workingnomads.com/jobs",       "api": "https://www.workingnomads.com/api/exposed_jobs/", "type": "json_api"},
    {"id": "jobspresso",        "url": "https://jobspresso.co/",                   "type": "scrape"},
    {"id": "remoteco",          "url": "https://remote.co/remote-jobs/",           "type": "scrape"},
    {"id": "justremote",        "url": "https://justremote.co/",                   "type": "scrape"},
    {"id": "remotehub",         "url": "https://remotehub.com/",                   "type": "scrape"},
    {"id": "virtualvocations",  "url": "https://www.virtualvocations.com/",        "type": "scrape"},
    {"id": "flexjobs",          "url": "https://www.flexjobs.com/",                "type": "scrape",   "notes": "Paid membership — use sparingly"},
    {"id": "problogger",        "url": "https://problogger.com/jobs/",             "type": "scrape"},
    {"id": "bloggingpro",       "url": "https://www.bloggingpro.com/jobs/",        "type": "scrape"},
    {"id": "mediabistro",       "url": "https://www.mediabistro.com/jobs/",        "type": "scrape"},
    {"id": "journalismjobs",    "url": "https://www.journalismjobs.com/",          "type": "scrape"},
    {"id": "indeed",            "url": "https://www.indeed.com/",                  "type": "serper",   "query_suffix": "remote contract freelance"},
    {"id": "linkedin",          "url": "https://www.linkedin.com/jobs/",           "type": "serper",   "query_suffix": "remote contract"},
    {"id": "glassdoor",         "url": "https://www.glassdoor.com/",               "type": "serper"},
]

# ──────────────────────────────────────────────────────────────────────────────
# REDDIT SUBREDDITS — scraped for hiring posts and opportunities
# ──────────────────────────────────────────────────────────────────────────────

REDDIT_SUBS = [
    "beermoney",            # General online earning
    "WorkOnline",           # Remote/online work opportunities
    "slavelabour",          # Small paid tasks
    "forhire",              # Hiring posts
    "hiring",               # Job postings
    "freelance",            # Freelance discussion + jobs
    "Upwork",               # Upwork tips + job leads
    "mturk",                # MTurk community
    "transcription",        # Transcription jobs
    "VirtualAssistant",     # VA jobs
    "outlier_ai",           # Outlier.ai community
    "SurgeAI",              # Surge AI community
    "ESL",                  # English teaching gigs
    "Tutoring",             # Tutoring gigs
    "VoiceActing",          # Voice acting leads
    "copywriting",          # Writing gigs
    "freelanceWriters",     # Writing community + jobs
    "socialmedia",          # SMM opportunities
    "digital_marketing",    # Marketing gigs
    "buhay_pilipinas",      # Pinoy remote workers (many global gig platforms)
    "OnlineESLTeaching",    # ESL teaching leads
    "learnmachinelearning", # ML data annotation leads
    "artificial",           # AI community
]

# ──────────────────────────────────────────────────────────────────────────────
# DISCOVERY QUERY TEMPLATES
# Combines category keywords with platform/board context
# ──────────────────────────────────────────────────────────────────────────────

SERPER_QUERY_TEMPLATES = [
    # Find new platforms by category
    '"{keyword}" site:greenhouse.io OR site:lever.co',
    '"{keyword}" remote freelance contract 2025',
    '"{keyword}" hiring site:remoteok.com',
    '"{keyword}" apply now remote',
    # Find discussions with links
    '"{keyword}" reddit.com how to get hired',
    # Find new companies
    '"{keyword}" company hiring contractors 2025',
]

# Quick lookup: category_id → priority (for scheduling)
DISCOVERY_PRIORITY = {
    "ai_training":          1,   # Check daily
    "data_annotation":      1,
    "search_rating":        1,
    "ux_testing":           2,   # Check every 2 days
    "software_testing":     2,
    "transcription":        2,
    "content_writing":      2,
    "virtual_assistant":    2,
    "customer_service":     3,   # Weekly
    "content_moderation":   3,
    "online_tutoring":      2,
    "translation":          2,
    "online_research":      3,
    "bookkeeping_finance":  3,
    "voice_audio":          3,
    "design_creative":      3,
    "ecommerce_support":    3,
    "social_media":         3,
    "surveys_research":     4,   # Monthly check — low ROI
    "coding_freelance":     2,
}

if __name__ == "__main__":
    total_platforms = sum(len(c["platforms"]) for c in CATEGORIES)
    print(f"Categories:   {len(CATEGORIES)}")
    print(f"Platforms:    {total_platforms}")
    print(f"Job boards:   {len(JOB_BOARDS)}")
    print(f"Subreddits:   {len(REDDIT_SUBS)}")
    all_kw = [kw for c in CATEGORIES for kw in c["keywords"]]
    print(f"Keywords:     {len(all_kw)}")
    ats = [s for c in CATEGORIES for s in c.get("ats_slugs", [])]
    print(f"ATS slugs:    {len(ats)}")
