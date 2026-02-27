import json
import os
import re
import httpx
import diskcache
import certifi
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from neo4j import GraphDatabase
import asyncio

os.environ["SSL_CERT_FILE"] = certifi.where()

app = FastAPI()
cache = diskcache.Cache(".cache/gemini")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"
MODEL = "gemini-3-flash-preview"

if GEMINI_API_KEY:
    print(f"[STARTUP] GEMINI_API_KEY is set ({len(GEMINI_API_KEY)} chars)", flush=True)
else:
    print("[STARTUP] WARNING: GEMINI_API_KEY is NOT set! API calls will fail.", flush=True)

# --- Neo4j (Bolt driver) ---
NEO4J_URI = os.environ.get("NEO4J_URI", "")  # e.g. neo4j+s://cc16b147.databases.neo4j.io
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
neo4j_driver = None

if NEO4J_URI and NEO4J_PASSWORD:
    try:
        neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
        neo4j_driver.verify_connectivity()
        print(f"[STARTUP] Neo4j connected to {NEO4J_URI}", flush=True)
    except Exception as e:
        print(f"[STARTUP] WARNING: Neo4j connection failed: {e}", flush=True)
        neo4j_driver = None
else:
    print("[STARTUP] Neo4j not configured (set NEO4J_URI and NEO4J_PASSWORD)", flush=True)


def store_analysis(headline, branches):
    """Store a completed analysis in Neo4j as a graph."""
    if not neo4j_driver:
        print("[NEO4J] Skipping store — not configured", flush=True)
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        with neo4j_driver.session(database="neo4j") as session:
            # Create headline node
            session.run(
                "CREATE (h:Headline {text: $text, created_at: $now})",
                text=headline, now=now,
            )

            # Create each branch's causal chain
            for branch_idx, chain in enumerate(branches):
                if not chain:
                    continue
                session.run(
                    """
                    MATCH (h:Headline {text: $headline, created_at: $now})
                    CREATE (e:Prediction {text: $p0, agent: $a0, agent_id: $aid0, confidence: $c0, timeframe: $tf0, branch: $branch, depth: 0, created_at: $now})
                    CREATE (g:Prediction {text: $p1, agent: $a1, agent_id: $aid1, confidence: $c1, timeframe: $tf1, branch: $branch, depth: 1, created_at: $now})
                    CREATE (s:Prediction {text: $p2, agent: $a2, agent_id: $aid2, confidence: $c2, timeframe: $tf2, branch: $branch, depth: 2, created_at: $now})
                    CREATE (f:Prediction {text: $p3, agent: $a3, agent_id: $aid3, confidence: $c3, timeframe: $tf3, branch: $branch, depth: 3, created_at: $now})
                    CREATE (h)-[:CAUSES]->(e)
                    CREATE (e)-[:CAUSES]->(g)
                    CREATE (g)-[:CAUSES]->(s)
                    CREATE (s)-[:CAUSES]->(f)
                    """,
                    headline=headline, now=now, branch=branch_idx,
                    p0=chain[0]["prediction"], a0=chain[0]["agent"], aid0=chain[0]["agent_id"], c0=chain[0]["confidence"], tf0=AGENTS[0]["timeframe_label"],
                    p1=chain[1]["prediction"], a1=chain[1]["agent"], aid1=chain[1]["agent_id"], c1=chain[1]["confidence"], tf1=AGENTS[1]["timeframe_label"],
                    p2=chain[2]["prediction"], a2=chain[2]["agent"], aid2=chain[2]["agent_id"], c2=chain[2]["confidence"], tf2=AGENTS[2]["timeframe_label"],
                    p3=chain[3]["prediction"], a3=chain[3]["agent"], aid3=chain[3]["agent_id"], c3=chain[3]["confidence"], tf3=AGENTS[3]["timeframe_label"],
                )
                print(f"[NEO4J] Stored branch {branch_idx}", flush=True)

        print(f"[NEO4J] Stored analysis for: {headline[:60]}...", flush=True)
    except Exception as e:
        print(f"[NEO4J] Error storing analysis: {e}", flush=True)

NUM_BRANCHES = 4

YUTORI_API_KEY = os.environ.get("YUTORI_API_KEY", "")
YUTORI_BASE_URL = "https://api.yutori.com/v1"

# Each agent handles a specific time horizon and perspective.
# The Economist creates the initial branches (NUM_BRANCHES predictions).
# All subsequent agents are called ONCE PER BRANCH with that branch's context,
# producing exactly 1 prediction each, so each branch becomes a true causal chain.

AGENTS = [
    {
        "id": "economist",
        "name": "Economist",
        "icon": "chart",
        "color": "#4ecdc4",
        "timeframe_label": "days",
        "system": (
            "You are a sharp economist and market analyst. Given a news headline, "
            f"predict exactly {NUM_BRANCHES} distinct immediate economic consequences (within 1-3 days). "
            "Each must cover a DIFFERENT aspect (e.g. markets, trade, employment). "
            "Be specific, bold, and concise. Each prediction 1-2 sentences max. "
            'Return ONLY a JSON array: [{"prediction": "...", "confidence": "high/medium/low"}]'
        ),
    },
    {
        "id": "geopolitics",
        "name": "Geopolitical Strategist",
        "icon": "globe",
        "color": "#ff6b6b",
        "timeframe_label": "weeks",
        "system": (
            "You are a geopolitical strategist. You are given a news headline and a SPECIFIC "
            "economic consequence that followed from it. Predict exactly 1 geopolitical reaction "
            "that would follow FROM THIS SPECIFIC economic consequence within weeks. "
            "How do other nations react? What alliances shift? "
            "Be specific and concise. 1-2 sentences max. "
            'Return ONLY a JSON array with 1 item: [{"prediction": "...", "confidence": "high/medium/low"}]'
        ),
    },
    {
        "id": "domestic",
        "name": "Social Analyst",
        "icon": "people",
        "color": "#ffd93d",
        "timeframe_label": "months",
        "system": (
            "You are a domestic policy and social trends analyst. You are given a news headline "
            "and a SPECIFIC causal chain (economic consequence -> geopolitical reaction). "
            "Predict exactly 1 domestic social or cultural consequence that follows FROM THIS "
            "SPECIFIC chain within months. How does it affect everyday people? "
            "Be specific and concise. 1-2 sentences max. "
            'Return ONLY a JSON array with 1 item: [{"prediction": "...", "confidence": "high/medium/low"}]'
        ),
    },
    {
        "id": "longterm",
        "name": "Futurist",
        "icon": "rocket",
        "color": "#c084fc",
        "timeframe_label": "1-5 years",
        "system": (
            "You are a futurist and long-term trend forecaster. You are given a news headline "
            "and a SPECIFIC causal chain (economic -> geopolitical -> social consequences). "
            "Predict exactly 1 long-term paradigm shift (1-5 years) that follows FROM THIS "
            "SPECIFIC chain. What does the world look like? "
            "Be bold, imaginative but grounded. 1-2 sentences max. "
            'Return ONLY a JSON array with 1 item: [{"prediction": "...", "confidence": "high/medium/low"}]'
        ),
    },
]


def extract_json_array(text):
    """Robustly extract a JSON array from LLM output."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if match:
        raw = re.sub(r"\*\*", "", match.group(0))
        arr = json.loads(raw)
        for item in arr:
            if "prediction" in item:
                item["prediction"] = re.sub(r"\*\*", "", item["prediction"])
        return arr
    raise ValueError(f"No JSON array found in: {text[:200]}")


def call_gemini(system_prompt, user_content, max_retries=5, timeout=10.0):
    """Make a single Gemini API call and return parsed predictions. Results are cached to disk."""
    cache_key = f"{MODEL}:{system_prompt}:{user_content}"
    cached = cache.get(cache_key)
    if cached is not None:
        print(f"\n[CACHE HIT] {user_content[:80]}...", flush=True)
        return cached

    if not GEMINI_API_KEY:
        print("[GEMINI] ERROR: GEMINI_API_KEY is not set!", flush=True)
        raise ValueError("GEMINI_API_KEY environment variable is not set")

    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n[GEMINI] Attempt {attempt}/{max_retries} — {MODEL}...", flush=True)
            print(f"[GEMINI] User: {user_content[:80]}...", flush=True)
            with httpx.Client(timeout=timeout) as http_client:
                response = http_client.post(
                    f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                    json={
                        "systemInstruction": {"parts": [{"text": system_prompt}]},
                        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
                        "generationConfig": {
                            "temperature": 0.8,
                            "maxOutputTokens": 1024,
                        },
                    },
                )
                print(f"[GEMINI] Status: {response.status_code}", flush=True)
                if response.status_code != 200:
                    print(f"[GEMINI] Error body: {response.text[:500]}", flush=True)
                response.raise_for_status()
                text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            print(f"[GEMINI] Response: {text[:120]}...", flush=True)
            result = extract_json_array(text)
            cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"[GEMINI] Attempt {attempt} failed: {e}", flush=True)
            if attempt == max_retries:
                print(f"[GEMINI] FAILED after {max_retries} attempts: {user_content[:80]}...", flush=True)
                raise


async def generate_butterfly_effect(headline):
    """
    Architecture:
      1. Economist produces NUM_BRANCHES predictions (the initial fan-out)
      2. For each subsequent agent, we call it ONCE PER BRANCH
         with only that branch's causal chain as context
      3. This creates NUM_BRANCHES independent causal chains,
         each flowing: Economist -> Geopolitics -> Social -> Futurist
    """

    yield {"event": "start", "data": json.dumps({"headline": headline})}

    # --- Step 1: Economist creates the branches ---
    agent = AGENTS[0]
    yield {
        "event": "agent_start",
        "data": json.dumps({
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "color": agent["color"],
            "icon": agent["icon"],
        }),
    }
    await asyncio.sleep(0.3)

    # branches[i] = list of predictions in that branch's causal chain
    branches = [[] for _ in range(NUM_BRANCHES)]

    try:
        preds = await asyncio.to_thread(
            call_gemini, agent["system"], f"NEWS HEADLINE: {headline}"
        )
        # Ensure we have exactly NUM_BRANCHES
        preds = preds[:NUM_BRANCHES]

        for i, pred in enumerate(preds):
            branches[i].append({
                "agent": agent["name"],
                "agent_id": agent["id"],
                "prediction": pred["prediction"],
                "confidence": pred.get("confidence", "medium"),
            })
            yield {
                "event": "prediction",
                "data": json.dumps({
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "color": agent["color"],
                    "icon": agent["icon"],
                    "prediction": pred["prediction"],
                    "timeframe": agent["timeframe_label"],
                    "confidence": pred.get("confidence", "medium"),
                    "branch": i,
                    "depth": 0,
                }),
            }
            await asyncio.sleep(0.15)
    except Exception as e:
        yield {"event": "error", "data": json.dumps({"agent_id": agent["id"], "error": str(e)})}

    yield {"event": "agent_done", "data": json.dumps({"agent_id": agent["id"]})}

    # --- Step 2: Each subsequent agent is called once per branch ---
    # All 4 branch calls run in PARALLEL, then results are yielded sequentially
    for depth, agent in enumerate(AGENTS[1:], start=1):
        yield {
            "event": "agent_start",
            "data": json.dumps({
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "color": agent["color"],
                "icon": agent["icon"],
            }),
        }
        await asyncio.sleep(0.3)

        # Build contexts for all branches, then fire calls in parallel
        async def call_branch(branch_idx, agent=agent):
            chain = branches[branch_idx]
            if not chain:
                return branch_idx, None, None
            context = f"NEWS HEADLINE: {headline}\n\n"
            context += "THE CAUSAL CHAIN SO FAR (each step caused the next):\n"
            for step_num, step in enumerate(chain, 1):
                context += f"  Step {step_num} [{step['agent']}]: {step['prediction']}\n"
            context += "\nPredict the NEXT domino in this specific chain."
            try:
                preds = await asyncio.to_thread(call_gemini, agent["system"], context)
                return branch_idx, preds[0], None
            except Exception as e:
                return branch_idx, None, e

        # Fire all branch calls in parallel
        results = await asyncio.gather(*[call_branch(i) for i in range(NUM_BRANCHES)])

        # Yield results sequentially to the UI
        for branch_idx, pred, error in results:
            if error is not None:
                yield {"event": "error", "data": json.dumps({"agent_id": agent["id"], "branch": branch_idx, "error": str(error)})}
                continue
            if pred is None:
                continue

            branches[branch_idx].append({
                "agent": agent["name"],
                "agent_id": agent["id"],
                "prediction": pred["prediction"],
                "confidence": pred.get("confidence", "medium"),
            })

            yield {
                "event": "prediction",
                "data": json.dumps({
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "color": agent["color"],
                    "icon": agent["icon"],
                    "prediction": pred["prediction"],
                    "timeframe": agent["timeframe_label"],
                    "confidence": pred.get("confidence", "medium"),
                    "branch": branch_idx,
                    "depth": depth,
                }),
            }
            await asyncio.sleep(0.15)

        yield {"event": "agent_done", "data": json.dumps({"agent_id": agent["id"]})}

    total = sum(len(b) for b in branches)

    # Store the full analysis in Neo4j
    await asyncio.to_thread(store_analysis, headline, branches)

    yield {"event": "complete", "data": json.dumps({"total_predictions": total})}


@app.get("/")
async def root():
    return FileResponse("index.html")


@app.get("/analyze")
async def analyze(headline: str):
    return EventSourceResponse(generate_butterfly_effect(headline))


@app.get("/history")
async def history():
    """Return all past analyses from Neo4j."""
    if not neo4j_driver:
        return JSONResponse({"error": "Neo4j not connected"}, status_code=503)
    def _query():
        with neo4j_driver.session(database="neo4j") as session:
            result = session.run(
                "MATCH (h:Headline)-[:CAUSES*]->(p:Prediction) "
                "WITH h, p ORDER BY p.branch, p.depth "
                "WITH h, collect({text: p.text, agent: p.agent, confidence: p.confidence, "
                "branch: p.branch, depth: p.depth, timeframe: p.timeframe}) AS predictions "
                "RETURN h.text AS headline, h.created_at AS created_at, predictions "
                "ORDER BY h.created_at DESC"
            )
            return [dict(r) for r in result]
    rows = await asyncio.to_thread(_query)
    return JSONResponse(rows)


def fetch_news_from_gemini():
    """Fetch news headlines from Gemini with a higher token limit than call_gemini."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable is not set")

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={
                "systemInstruction": {"parts": [{"text":
                    "You are a news aggregator. Return ONLY a JSON array, no other text."
                }]},
                "contents": [{"role": "user", "parts": [{"text":
                    "Top 5 breaking news headlines today. Politics, economics, tech, geopolitics. "
                    'Return ONLY: [{"headline":"...","summary":"1 short sentence","source":"source"}]'
                }]}],
                "generationConfig": {"temperature": 0.8, "maxOutputTokens": 4096},
            },
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return extract_json_array(text)


@app.get("/news")
async def get_news():
    """Get news feed. Returns cached headlines or fetches from Gemini on first call."""
    cached = cache.get("news_feed")
    if cached is not None:
        return JSONResponse({"headlines": cached, "source": "cache"})

    try:
        result = await asyncio.to_thread(fetch_news_from_gemini)
        cache.set("news_feed", result)
        return JSONResponse({"headlines": result, "source": "google"})
    except Exception as e:
        return JSONResponse({"headlines": [], "source": "error", "error": str(e)})


@app.get("/news/refresh")
async def refresh_news_yutori():
    """Try to get fresh news from Yutori Browsing API. Client should use a 20s timeout."""
    if not YUTORI_API_KEY:
        return JSONResponse({"headlines": [], "source": "no_key"})

    headers = {"X-API-Key": YUTORI_API_KEY, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{YUTORI_BASE_URL}/browsing/tasks",
                headers=headers,
                json={
                    "task": "Extract the top 8 current breaking news headlines with a 1-sentence summary for each. Focus on politics, economics, technology, and world events.",
                    "start_url": "https://apnews.com",
                    "max_steps": 15,
                    "output_schema": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "headline": {"type": "string", "description": "Short news headline"},
                                "summary": {"type": "string", "description": "1-sentence summary"},
                                "source": {"type": "string", "description": "News source name"},
                            },
                        },
                    },
                },
            )
            resp.raise_for_status()
            task_id = resp.json()["task_id"]

            for _ in range(6):
                await asyncio.sleep(3)
                status_resp = await client.get(
                    f"{YUTORI_BASE_URL}/browsing/tasks/{task_id}",
                    headers={"X-API-Key": YUTORI_API_KEY},
                )
                status_resp.raise_for_status()
                data = status_resp.json()

                if data["status"] == "succeeded":
                    headlines = data.get("structured_result") or []
                    if headlines:
                        cache.set("news_feed", headlines)
                    return JSONResponse({"headlines": headlines, "source": "yutori"})
                elif data["status"] == "failed":
                    return JSONResponse({"headlines": [], "source": "yutori_failed"})

    except Exception as e:
        return JSONResponse({"headlines": [], "source": "yutori_error", "error": str(e)})

    return JSONResponse({"headlines": [], "source": "yutori_timeout"})
