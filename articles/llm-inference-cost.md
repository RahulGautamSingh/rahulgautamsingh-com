# The agent that paid to re-read its own homework

Published October 2026 · @Rahul Gautam Singh

*How a supplier-discovery tool loop quietly billed us for the same scraped pages five times over, and the three PRs that stopped it.*

**TL;DR.** A tool loop budgeted at six model calls was re-sending every previous scrape on every call, so input-token cost grew with the square of the loop length, not linearly. It surfaced as context-limit failures and roughly one dollar per call. Capping scrape size, splitting discovery from enrichment, and finally moving scraping out of the loop entirely took inference cost down by around 70%. None of it made the model faster. It made the model stop re-reading things.

## What the thing does

At Unibloom we built supplier discovery: you ask for alternatives to a supplier, and an agent goes and finds them. Search the web, scrape the promising pages, return structured candidates with a sustainability profile attached.

It is a tool loop, not a pipeline. The implementation is `generateText` from the Vercel AI SDK with `stopWhen: stepCountIs(...)` — six for finding alternatives, five for analysing a current supplier. Models were `gpt-5.4-mini` and Gemini, through the plain `@ai-sdk/openai` and `@ai-sdk/google` providers.

## What a "step" actually is

This is the part worth getting right, because the word invites the wrong picture.

A step is **one model generation**. On each one the model either calls tools — in which case the results are appended to the message history and another step runs — or it emits its final output, which ends the loop early. So `stepCountIs(6)` does not describe six scripted stages. It says: *the model gets at most six generations before it has to answer.*

What happened inside those six was steered entirely by the prompt, which prescribed a loose two-phase method rather than a per-step script:

- Use the search tool to find promising official supplier pages.
- Scrape the strongest ones before returning candidates.
- Return JSON matching the schema, up to six candidates.

A typical run came out as:

1. **Step 1** — the model calls search. Twelve SERP results come back and get appended.
2. **Steps 2 to 5** — it calls scrape on the pages it liked, sometimes several in one step since the SDK allows parallel tool calls. Each scrape returned up to **16,000 characters** of raw Firecrawl markdown. All of it appended. It could interleave more searches here too.
3. **Final step** — it emits the structured JSON. If it had not finished by step six, the loop was cut off there.

So the shape of a run was emergent. Some finished in three generations, some used all six.

## Why that gets expensive

Each step is a fresh, stateless call to the model. Nothing between steps is summarised or dropped. **Step N re-sends everything from steps 1 through N−1**, and you pay input tokens for the whole pile every time.

By the last generation the model was re-reading the system prompt, the twelve search results, and potentially four or five scrapes at 16,000 characters each. Not because it needed them again, but because that was the context.

The cost does not scale with the number of steps. It scales with the square of it. A rough illustration, assuming each step adds a similar lump of context:

| Step | Carried in | Billed input |
| --- | --- | --- |
| 1 | 0 | 1 unit |
| 2 | 1 | 2 units |
| 3 | 2 | 3 units |
| 4 | 3 | 4 units |
| 5 | 4 | 5 units |
| 6 | 5 | 6 units |
| | **Total content: 6** | **Total billed: 21** |

Six units of actual content, twenty-one units billed. Add a seventh step and you do not add one unit, you add seven.

This is invisible in development. You test with a short document and two tool calls, the bill is cents, and the curve never shows itself. It shows up in production, on real pages, at real volume.

## How it surfaced

Not as a line on an invoice. It surfaced as **context-limit failures** — runs that simply died because the accumulated history no longer fitted — and as individual calls costing **roughly a dollar**.

A dollar per supplier query is not a rounding error on a product where querying is the whole point. The failures were the louder signal, but the cost was the one that made it urgent.

## Three fixes, same multiplier

Each attacked the same problem from a different distance.

**Cap the characters per scrape.** The 16,000-character ceiling was generous for a page you read once and absurd for a page you re-read five times. Lowering it cuts every subsequent re-send at the same time. The cheapest change and the first one worth making.

**Split discovery from enrichment.** Instead of one loop that searches, scrapes and composes, two narrower passes that each carry less context. The expensive material stops travelling through generations that have no use for it.

**Move scraping out of the loop entirely.** The real fix. If scraping happens outside the model's tool loop, the raw markdown never enters the message history at all. The model gets what it needs to decide, not the pages themselves. The multiplier does not get smaller — it stops existing.

The same PR made the system prompts static. They had been built per call; as module-level constants they are identical byte-for-byte on every request, which matters for the next point.

## A caveat about caching

We had no explicit prompt-caching code. No `cache_control`, no `cacheControl`, no `promptCacheKey` anywhere in the AI calls. The only `cacheControl` in the codebase reads an HTTP response header in a URL-validation tool.

But **"no explicit caching" is not the same as "no caching."** OpenAI applies automatic server-side prompt caching regardless of what you do, so some of that repeated prefix was already cheaper than list price. Making the system prompts static helps precisely because caching keys on an identical prefix.

I am making the narrow claim here, not the broad one: we wrote no caching code. What the provider did underneath is theirs, and I did not measure it.

## What I would tell someone starting this

**Log input tokens per step, not per call.** A single aggregate number hides the quadratic shape completely. Per step, the growth is obvious on the first chart you draw.

**Find the biggest thing that enters the history and ask whether it has to.** Cost concentrates wherever bulk text joins the context — scraped pages, retrieved documents, long tool output. Everything downstream pays for it, repeatedly.

**Prefer moving work out of the loop over trimming what is in it.** Capping the scrape size was worth doing and it was still a smaller win than taking scraping out of the loop. Trimming reduces the multiplier; removal deletes it.

**Mind the vocabulary.** "Six steps" sounds like six stages of a pipeline. It is a budget of six model generations, and the difference matters when you are reasoning about what gets re-sent.

None of this is clever. It is the LLM equivalent of noticing a query inside a loop. But the pricing model makes it expensive in a way ordinary redundant work is not, and nothing in the developer experience points at it — the code that carries everything forward is the code that reads most naturally.
