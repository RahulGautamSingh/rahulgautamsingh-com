# The agent that paid to re-read its own homework

Published October 2026 · @Rahul Gautam Singh

*A supplier-discovery tool loop re-sent every page it had scraped on every model call. Three weeks and four PRs to stop it, only one of which was mine.*

**TL;DR.** In April 2026 our supplier-discovery agent started failing on context limits and costing around a dollar a call. The cause was structural: in a tool loop, step N re-sends everything from steps 1 to N−1, so when each scrape appends 16,000 characters of raw markdown, cost grows superlinearly with loop length. The fixes came in three waves from two people — cap the scrape size, split discovery from enrichment, then take scraping out of the loop entirely. I own the second one. The numbers below are flagged where they are recollection rather than measurement.

## What it does

At Unibloom, supplier discovery answers "find me alternatives to this supplier." An agent searches the web, scrapes promising pages, and returns structured candidates with a sustainability profile attached — EcoVadis, CDP, SBTi, Scope 3, EUDR, REACH.

It is a tool loop, not a pipeline. `generateText` from the Vercel AI SDK, `stopWhen: stepCountIs(n)`, two tools: search and scrape. Models were `gpt-5.4-mini` and Gemini through the plain `@ai-sdk/openai` and `@ai-sdk/google` providers.

I built that first version in PR #343, merged 2 April 2026, with Shivansh Kumar. The original budgets were six tool steps and a 16,000-character scrape cap for the alternatives flow, five steps and 14,000 characters for analysing a current supplier.

## What a "step" actually is

Worth getting right, because the word invites the wrong picture.

A step is **one model generation**. On each one the model either calls tools — results get appended to the message history and another step runs — or it emits final output, ending the loop early. So `stepCountIs(6)` does not describe six scripted stages. It says *the model gets at most six generations before it has to answer.*

What happened inside was steered only by the prompt, which gave a loose two-phase method rather than a per-step script: use search to find promising official pages, scrape the strongest ones, then return JSON matching the schema.

A typical run came out as:

1. **Step 1** — call search. Twelve SERP results appended.
2. **Steps 2 to 5** — call scrape on pages it liked, sometimes several per step since the SDK allows parallel tool calls. Each scrape returned up to 16,000 characters of raw Firecrawl markdown, truncated with a `[Content truncated to N chars]` marker. All appended. It could interleave more searches.
3. **Final step** — emit the `Output.object` JSON. If it had not finished by six, the loop was cut off there.

So the shape was emergent. Some runs finished in three generations, some used the lot.

## Why that gets expensive

Each step is a fresh, stateless call. Nothing between steps is summarised or dropped. **Step N re-sends everything from steps 1 through N−1**, and you pay input tokens for the whole pile every time.

By the last generation the model was re-reading the system prompt, twelve search results, and potentially four or five scrapes at 16,000 characters each. Not because it needed them again. Because that was the context.

Cost scales with the square of the loop length, not with it. A rough illustration, assuming each step adds a similar lump:

| Step | Carried in | Billed input |
| --- | --- | --- |
| 1 | 0 | 1 unit |
| 2 | 1 | 2 units |
| 3 | 2 | 3 units |
| 4 | 3 | 4 units |
| 5 | 4 | 5 units |
| 6 | 5 | 6 units |
| | **content: 6** | **billed: 21** |

Six units of content, twenty-one billed. Add a seventh step and you add seven, not one.

Invisible in development. You test with a short page and two tool calls, the bill is cents, the curve never shows itself.

## How it surfaced

Not as a line on an invoice. As **context-limit failures** — runs dying because the accumulated history no longer fitted — and calls costing **roughly a dollar**.

Both of those figures are my recollection from the time. See the note on evidence at the end.

## Three waves, same multiplier

**Cap the scrape, 15 April (PR #411, Shivansh Kumar).** The first and biggest ratchet: alternatives 16,000 → 5,000 characters, current supplier 14,000 → 3,000. Lowering the cap cuts every subsequent re-send at the same time, which is why it was the cheapest effective change available. The same PR added a URL-validation tool so the model stopped scraping dead links.

**Split discovery from enrichment, 17 April (PR #416, mine).** This one I own. Discovery had been returning the full candidate schema — including the whole sustainability profile — from inside the loop that was also doing the scraping. I split the data contract in two: discovery now returns basic candidates (name, URL, location, cost, flags), and a separate enrichment phase returns the sustainability and operational detail keyed by supplier.

The point was not the schema. It was that expensive evidence-gathering stopped happening inside the discovery loop, so each loop carried less. Enrichment got its own budget: ten steps, six results, 5,000 characters.

**Take scraping out of the loop, 22–23 April (PR #421, Shivansh Kumar, with Vinod Kumar and me).** The real fix. Exa does discovery, Firecrawl is called with a nine-field extraction schema, and both run *outside* the model loop. The data contract changed from a raw markdown blob to structured JSON, capped at 4,000 characters per candidate. Analysis then runs as a single `generateText` with no tools at all, over pre-scraped structured data.

The model never sees a raw page again. The multiplier does not get smaller — it stops existing.

## The bit that wasn't monotonic

Between the second and third waves, on 18 April, I raised all three step budgets from ten to fifteen (PR #418) and reworked the tool-usage instructions.

That moved step counts *up*, not down. The honest framing is that I traded per-scrape size for more, smaller steps — with a 5,000-character cap, more generations were affordable than they had been at 16,000. The final rewrite brought them back down to eight for enrichment and ten for discovery.

Cost work does not progress in a straight line, and a write-up that only lists the reductions is a tidier story than the one that happened.

## A caveat on caching

We had no explicit prompt-caching code. No `cache_control`, no `cacheControl`, no `promptCacheKey` in any AI call. `providerOptions` was used only for `{ strictJsonSchema: false }`.

But **"no explicit caching" is not "no caching."** OpenAI applies automatic server-side prompt caching regardless. Making the system prompts static — module-level constants and zero-arg builders, part of the final PR — helps precisely because caching keys on an identical prefix.

I am making the narrow claim, not the broad one.

## What the numbers can and cannot support

The repository contains no token counts, no dollar amounts, no failure rates. The dollar-a-call figure and the overall reduction are my recollection. Where they could be verified: LLM telemetry went into PostHog on 1 April (PR #362, Vinit Sarvade), which predates all of this work, so before-and-after curves would live there. Context-length errors would be queryable in the error table by date and message.

What the code alone supports, without claiming a measurement: worst-case context went from roughly six generations accumulating 16,000 characters of raw markdown each, to a single tool-less call over at most 4,000 characters of structured JSON per candidate. That arithmetic supports a large reduction on its own.

I would rather say that than quote a number I cannot currently reproduce.

## What I would tell someone starting this

**Log input tokens per step, not per call.** A single aggregate hides the quadratic shape completely.

**Find the biggest thing entering the history and ask whether it has to be there.** Cost concentrates where bulk text joins the context. Everything downstream pays for it, repeatedly.

**Prefer moving work out of the loop over trimming what is in it.** Capping the scrape was worth doing and still a smaller win than removing scraping from the loop. Trimming reduces the multiplier; removal deletes it.

**Mind the vocabulary.** "Six steps" sounds like six stages of a pipeline. It is a budget of six model generations, and the difference matters when you reason about what gets re-sent.

None of this is clever. It is the LLM equivalent of a query inside a loop. But the pricing model makes it expensive in a way ordinary redundant work is not, and nothing in the developer experience points at it — the code that carries everything forward is the code that reads most naturally.
