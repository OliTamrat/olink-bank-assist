# Market position — where this competes, and where it grows next

**Written:** 2026-08-12, from a working session that also shipped the
per-teller/per-language analytics breakdowns and two live production fixes.
This is the durable version of that conversation — see ADR-0016 for the
decisions it records.

## Where the product actually stands

Phase 1 is complete and live: 5 languages across all three string surfaces,
seven channel adapters (Telegram self-serve; Viber, the Meta trio and SMS
all pending a commercial or business step on the vendor's side), the live-teller handoff verified against
real WebRTC traffic, and a safety doctrine (tool-output-is-truth, allowlist
intents, machine-checked guardrail invariants) that is unusually rigorous for
a pre-revenue product. `CLAUDE.md` "Current state" is the live version of
this; do not duplicate the numbers here.

What has **not** happened yet: a signed pilot. CBE, Dashen and Awash are
unauthorized internal prototypes built from public information, each carrying
a mandatory disclaimer — see ADR-0009. "Live" today means the demo bot; it
does not mean a bank has agreed to anything.

## The competitive field

The mechanic this product leads with — a customer's conversation surviving a
handoff from AI to a live human, across channels, with nothing repeated — is
not novel. **Glia** already sells exactly that, at scale, to 700+ US banks
and credit unions, under a "ChannelLess" architecture with flat per-institution
pricing. Any pitch that leads with "nobody else does live handoff" is wrong
and will be caught by anyone who has shopped this category.

What Glia does not have: Telegram as a first channel, native-language
guardrail work for Amharic/Afaan Oromo/Tigrinya/Somali, an in-country data
residency posture, or a price and deployment speed a single bank or MFI can
say yes to rather than an enterprise contract. That combination is real
whitespace — confirmed by looking, not assumed.

Locally, several Nigerian and Kenyan banks already run channel-specific bots
(Zenith's ZiVA, Access's Tamara, UBA's Leo, Equity's EVA, among others) —
proof of real regional appetite for exactly this category, and also the
"before" picture: single-channel, bank-built, no evidence of cross-channel
continuity or a live-human handoff in the same conversation. That gap between
what exists locally and what this product does is the pitch, not a guess
about demand.

## Positioning: prove narrow, market wide — but foundation-first, not
## contract-gated

The instinct to only advertise "Ethiopian banking" undersells a genuinely
horizontal capability: multilingual detection tuned by native speakers,
multi-channel with no lost context on handoff, tool-output-is-truth
guardrails, strict per-tenant isolation, and — for regulated industries
specifically — an in-country data-residency posture backed by real
INSA-certification experience from Onekof. That pattern reaches insurance
(claims/coverage Q&A has nearly the same shape as the account guardrail — a
hard boundary around anything requiring a license to say), telecom and MFIs
(same regulatory shape, already-huge WhatsApp/USSD presence, high call-center
cost), and eventually government citizen services, where the residency story
carries even more weight.

The correction worth recording: **the story does not need to wait on a
signed contract to be credible.** A pilot sharpens it further, but what
actually makes an expansion story believable is depth, not paperwork — and
this product already has real depth: the account guardrail's multi-round
native-phrasing history, the machine-checked general-knowledge boundary, the
two-report analytics design. Building the foundation right, aimed at a real
pain point rather than at a hypothetical buyer, is what makes the expansion
easy later — chase business impact first, and a securable customer is a
consequence of that, not a precondition for talking about what's next.

**The cost of this position, stated plainly (an ADR — and a market thesis —
with no downside listed is marketing):** claiming five industries with zero
production deployments risks sounding thinner than claiming one industry with
real depth. The mitigation is sequencing, not silence — lead every
conversation with the concrete, verifiable thing (the guardrail rigor, the
language work, the live-teller traffic numbers), and let the horizontal claim
follow the specific one, not replace it.

## Ethiopia's structural advantage beyond the banking vertical

Addis Ababa is the headquarters city of the African Union and hosts a dense
concentration of international and diplomatic institutions — a genuine,
underused go-to-market advantage distinct from the banking-sector case.
Establishing real traction in the Ethiopian market puts the company in
regular contact with continental business and policy leaders who would
otherwise take years of travel and cold outreach to reach. This is a reason
to go deep in Ethiopia first that has nothing to do with data-residency law
or Telegram penetration — it is a network effect available nowhere else on
the continent, and it compounds the "prove narrow" case above rather than
competing with it.

## Expanding language coverage

Requirements, in the order the cost actually falls (not the order the work
looks like from outside):

1. **String tables** — mechanical. Draft via MT, ship, native-review after.
   Same loop already run for the current five (`scripts/i18n_export.py`,
   the linguist TSV workflow — see ADR-0008).
2. **Language detection** (`classifier.detect_language`) — one disambiguation
   rule per language: a script tell for Ethiopic languages, an elimination
   rule for Latin-script ones. Hours, not a redesign.
3. **BM25 stopwords** — required, not optional. Amharic shipped without one
   first and was held to roughly 3x the informativeness bar of English for
   identical questions, because its function words were being scored as
   content. `_STOPWORDS_{LANG}` per language, merged into the shared frozen
   set — see `tests/test_language_parity.py`.
4. **Golden-question evals and adversarial phrasings** for the new language,
   so a future change cannot silently regress it.
5. **The account guardrail and every other security rule.** This is where
   Amharic, Afaan Oromo, Tigrinya and Somali cost the most: not translation,
   but native-informed rules for how someone actually asks for someone
   else's account, or reports a forgotten PIN with no "give me" verb. Five
   rounds of native phrasing testing on those four languages found real
   holes each round, including one that blocked a *legitimate* transfer.

**Point 5 is materially lighter for the next languages under discussion.**
Swahili, Hausa, Yoruba and Igbo are not starting from the same position
Amharic, Afaan Oromo, Tigrinya and Somali did. They already have substantial
representation in mainstream AI and NLP tooling — far more training data,
tokenizer coverage, and general-purpose language-model support exist for
them today than existed for the Ethiopian languages when this product's
guardrails were first built from a standing start. The native-review step
still matters and still ships before a language is called done — a banking
guardrail is not a place to skip verification because the underlying model
is stronger — but the discovery phase (finding the four-way disambiguation
Oromo needed, or the verb-based third-party signal Amharic needed) should be
shorter, because there is far more existing linguistic tooling and reference
material to start from.

**Native-speaker review resourcing is being handled directly** rather than
tracked here as an open risk.

**Swahili shipped 2026-08-12 — first-pass, not reviewed.** See ADR-0018 for
the full record. The "point 5 is lighter" claim above was tested, not just
argued: the discovery phase for Swahili's account guardrail (the noun list,
the possessive pattern, the manager/person fence) needed no supplied native
phrasings the way all four Ethiopian languages did, and the one real bug
found — a conditional-infix trap in the "forgot PIN" rule — surfaced on the
first adversarial pass rather than needing the five rounds Amharic/Oromo
needed. That is one data point in favour of the claim, not proof it holds for
every language on the list below; native review still has to run before a
real pilot, exactly as this document already said.

**Regional focus narrowed to East Africa, 2026-08-12 — see ADR-0019.** The
Nigeria bundle below is **parked, not cancelled**: the market case (real
local precedent, a large reachable population) still holds and this document
is not walking it back. The founder's call is sequencing, not opportunity —
go deep in the region Swahili already anchors before making a second regional
jump to West Africa. Any next language work is evaluated against East
Africa's reach first.

**Parked — Nigeria bundle (Hausa, Yoruba, Igbo):**

- Real local precedent exists, not just an estimate: Nigerian banks (Zenith,
  Access, UBA, Fidelity, Heritage, Keystone) already run WhatsApp/Telegram
  bots, and at least one Nigerian digital bank markets "banking in Yoruba,
  Igbo, Hausa, and Pidgin" as an explicit differentiator. This is real
  whitespace whenever the regional call revisits it.
- **Arabic stays sequenced after the Nigeria bundle, not before it.** Reach
  is large (Sudan, North Africa) but right-to-left layout is real engineering
  across the widget and the admin panel, not a string-table change — this
  was never a candidate for the near-term list regardless of the regional
  question above.

## Roadmap sequencing (as decided this session)

~~**Build the global search bar first.**~~ **Shipped** (PR #125, merged
2026-08-12). Language expansion started immediately after, with Swahili —
see above.
