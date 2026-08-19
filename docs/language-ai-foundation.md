# The language-AI foundation

*Written 2026-08-19. This is the direction document for Olink's African
language AI capability — the layer under every product, not a product
itself. It exists so the ambition ("agents that speak our languages
fluently, for a continent") proceeds in an order that compounds instead of
an order that burns the runway. Review yearly; the model landscape moves
faster than this document should.*

## The position

Olink builds **regulated vertical products** (banking, school transport,
compliance) that happen to need world-class African-language capability.
That is a different business from building the horizontal language layer —
which is what Addis AI (Amharic/Afaan Oromo voice: ASR, TTS, the
Addis-፩-አሌፍ model), Lelapa AI (InkubaLM) and EthioNLP (EthioLLM,
Walia-LLM) are doing, several of them well-funded or grant-backed.

The moat is not a model. Models depreciate every time Google or OpenAI
ships. The moat is what we already hold and can deepen:

1. **Deployed products with real multilingual traffic** in a market with a
   data-residency law (Proclamation 1321/2024, Art. 22) foreign vendors
   can't easily satisfy.
2. **Domain evaluation sets nobody else has** — real customer utterances,
   graded by native speakers, in banking. These do not depreciate.
3. **INSA certification experience** (Onekof) — a credential for the
   government and enterprise conversations the National AI Policy (June
   2024, EAII) is opening.

So the rule: **buy or adapt the horizontal layer; own the vertical data,
the evals, and the deployments.** Partner with the model-builders before
competing with them.

## The build order

Each step is gated on the one before it. Skipping ahead is how the money
goes before the compounding starts.

### 1. Evaluation before anything (the asset)

A human-graded golden set per language: 200–400 real utterances pulled
from live traffic, graded by a native speaker on a fixed rubric —
*understood correctly? / register natural? / calqued from English? / would
a customer say this?* Bank Assist's 20 golden evals and the linguist
workbook are the seed; this extends them from "is the reply worded well"
to "was the customer understood", which is where every live-demo defect so
far has actually been.

Why first: LLM-as-judge is measurably unreliable here — judge–human
agreement runs ~80% for Swahili, under 60% for lower-resource languages,
and **Amharic scores lowest of all, with the Ge'ez script itself imposing
a reliability barrier** (BabelJudge, arXiv:2606.22329; "Lower-Resource,
Higher Scores", arXiv:2607.14480 — both 2026). The bias direction is
overestimation: an automated eval will say Amharic is fine when it isn't.
Only humans can grade this, so the graded set is the scarce asset.

### 2. Small task models, fine-tuned on our traffic

Comprehension — intent classification, language ID, entity/contact
extraction, query rewriting — is where a fine-tuned small encoder beats
both the regex floor and a frontier model. Bases exist with exactly our
footprint: EthioLLM/AfroXLMR cover Amharic, Afaan Oromo, Tigrinya, Somali
(+ Ge'ez, English). LoRA fine-tunes run on one GPU for tens of dollars.
The first concrete build: an intent classifier for `am`/`om` trained on
labeled Bank Assist traffic, A/B'd against the deterministic rules — as a
layer **above** the rules floor (the roadmap already requires this), never
replacing it.

### 3. Voice — the interface for the next hundred million users

Typing Ge'ez on a phone is slow; speaking isn't. Addis AI's whole thesis,
and it is correct. Every Olink product is text-in/text-out today.

ASR first (comprehension again), TTS second. The recipe is published
(Whisper fine-tuned on Amharic, arXiv:2503.18485) and the open data is
already sufficient to start: Sagalee (100 h real-world Oromo), the Ethio
Speech Corpora (391 h across six languages), WAXAL's Ethiopian subset
(~1,100 h across five), FLEURS, Common Voice, Dataset.ET. **Before
building: ask Addis AI about a partnership.** Their layer under our
products may be faster and cheaper than owning ASR, and the pilot
conversation costs one meeting.

### 4. Continued pretraining of an open model — last, and only when forced

CPT of a 4–12 B open model (the AfriqueLLM recipe: ~26 B tokens, Gemma
3 / Qwen 3 / Llama 3.1 bases; Lugha-Llama's run was ~355 H100-hours) is
real and increasingly cheap. Do it when **both** hold: a residency
requirement forces self-hosting anyway (Art. 22 already trends there for
Phase 3), **and** we hold in-language data others don't (step 5). Until
then it's someone else's race. A from-scratch foundation model is a
national-champion project with government money, and stays off this list.

## Two numbers that shape architecture now

- **The Amharic token tax.** Frontier tokenizers charge Amharic a
  2.5–9.7× token premium — up to 7.4× inference cost and the same
  multiplier on latency; tokenizer choice alone is worth ~75% ("The
  African Language Tax", arXiv:2606.24460). Consequence: **instrument
  per-language cost, latency and answer rate in every product.** An
  Amharic conversation that quietly costs five times an English one, on a
  worse connection, is invisible in aggregate numbers — and it reprices
  the product.
- **Judges lie about Amharic** (step 1 above). Any pipeline that scores
  Ge'ez-script output with a model must carry a human-graded calibration
  set beside it, or its numbers are decoration.

## The data flywheel needs a legal design, not a code change

The most valuable training corpus in Ethiopia — real customers asking
real questions in Amharic and Afaan Oromo with outcome labels attached —
is generated by our products and deliberately not retained
(chat-text-is-never-logged is doctrine, and stays). The flywheel therefore
requires a **designed, consented path**: tenant-level opt-in in the
contract, customer notice, redaction before retention, a stated purpose,
Art. 22-compliant storage. Design it with counsel before Phase 3, because
retrofitting consent is not a thing. Until then, the handoff rows and
content-gap signatures we do keep are the legitimate starting corpus.

## Depth before breadth

Ethiopia's 80+ languages are the vision; they are not the operating
target. Amharic, Afaan Oromo, Tigrinya, Somali (+ Swahili regionally)
done to native-review quality is a defensible company; eighty at
first-pass quality is a demo. The gate for adding language N+1: the
existing languages have closed native review and a graded eval set. As of
this writing, Tigrinya, Somali and Swahili have not — that review, already
on the Phase 1 roadmap, is the actual next language milestone, not a new
language.

## Who to talk to, and about what

| Who | Why |
|---|---|
| Addis AI | Voice partnership before any ASR/TTS build |
| EthioNLP / Masakhane | Models with our exact language footprint; the community where the evaluators and annotators are (AfricaNLP is the venue) |
| Lacuna Fund, IDRC/AI4D, Google research awards, NVIDIA Inception | Non-dilutive money for exactly this: language datasets and compute |
| EAII / MInT | The National AI Policy promises startup incentives and PPPs; INSA experience is the door-opener |

## What this document refuses

- Training a foundation model from scratch.
- Adding languages before the current ones close native review.
- Responding to thin data by scraping harder (the import lesson,
  generalized: the good corpus is always the one you have to ask for).
- Relaxing chat-text-is-never-logged outside the consented path above.
- Model work before the graded eval set exists to measure it with.
