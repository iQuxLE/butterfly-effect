import json
import os
import re
import base64
import httpx
import diskcache
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
import asyncio

app = FastAPI()
cache = diskcache.Cache(".cache/gemini")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"
MODEL = "gemini-3-flash-preview"

if GEMINI_API_KEY:
    print(f"[STARTUP] GEMINI_API_KEY is set ({len(GEMINI_API_KEY)} chars)", flush=True)
else:
    print("[STARTUP] WARNING: GEMINI_API_KEY is NOT set! API calls will fail.", flush=True)

# --- Neo4j (Query API v2) ---
NEO4J_HOST = os.environ.get("NEO4J_HOST", "")  # e.g. cc16b147.databases.neo4j.io
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_URL = f"https://{NEO4J_HOST}/db/neo4j/query/v2" if NEO4J_HOST else ""
neo4j_auth = ""

if NEO4J_HOST and NEO4J_PASSWORD:
    neo4j_auth = base64.b64encode(f"{NEO4J_USERNAME}:{NEO4J_PASSWORD}".encode()).decode()
    print(f"[STARTUP] Neo4j configured: {NEO4J_HOST}", flush=True)
    # Test connectivity
    try:
        with httpx.Client(timeout=10.0) as c:
            resp = c.post(
                NEO4J_URL,
                headers={
                    "Authorization": f"Basic {neo4j_auth}",
                    "Content-Type": "application/json",
                },
                json={"statement": "RETURN 1 AS ok"},
            )
            print(f"[STARTUP] Neo4j connectivity test: {resp.status_code}", flush=True)
            if resp.status_code != 202:
                print(f"[STARTUP] Neo4j error: {resp.text[:300]}", flush=True)
    except Exception as e:
        print(f"[STARTUP] Neo4j connectivity test failed: {e}", flush=True)
else:
    print("[STARTUP] Neo4j not configured (set NEO4J_HOST and NEO4J_PASSWORD)", flush=True)


def neo4j_query(statement, parameters=None):
    """Execute a Cypher statement via the Neo4j Query API v2. Returns the response JSON."""
    if not neo4j_auth:
        return None
    body = {"statement": statement}
    if parameters:
        body["parameters"] = parameters
    with httpx.Client(timeout=30.0) as c:
        resp = c.post(
            NEO4J_URL,
            headers={
                "Authorization": f"Basic {neo4j_auth}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        print(f"[NEO4J] Query status: {resp.status_code}", flush=True)
        if resp.status_code != 202:
            print(f"[NEO4J] Error: {resp.text[:500]}", flush=True)
            return {"error": resp.text}
        return resp.json()


def store_analysis(headline, branches):
    """Store a completed analysis in Neo4j as a graph via Query API v2."""
    if not neo4j_auth:
        print("[NEO4J] Skipping store — not configured", flush=True)
        return
    try:
        now = datetime.now(timezone.utc).isoformat()

        # Build a single Cypher statement that creates the entire graph
        cypher = "CREATE (h:Headline {text: $headline, created_at: $now}) "
        params = {"headline": headline, "now": now}

        for branch_idx, chain in enumerate(branches):
            for depth, step in enumerate(chain):
                node_var = f"p{branch_idx}_{depth}"
                parent_var = f"p{branch_idx}_{depth - 1}" if depth > 0 else "h"
                cypher += (
                    f"CREATE ({node_var}:Prediction {{"
                    f"text: ${node_var}_text, agent: ${node_var}_agent, "
                    f"agent_id: ${node_var}_aid, confidence: ${node_var}_conf, "
                    f"branch: {branch_idx}, depth: {depth}, "
                    f"timeframe: ${node_var}_tf, created_at: $now}}) "
                    f"CREATE ({parent_var})-[:CAUSED]->({node_var}) "
                )
                params[f"{node_var}_text"] = step["prediction"]
                params[f"{node_var}_agent"] = step["agent"]
                params[f"{node_var}_aid"] = step["agent_id"]
                params[f"{node_var}_conf"] = step["confidence"]
                params[f"{node_var}_tf"] = AGENTS[depth]["timeframe_label"]

        cypher += "RETURN h.text AS headline"

        result = neo4j_query(cypher, params)

        if result and not result.get("error"):
            print(f"[NEO4J] Stored analysis for: {headline[:60]}...", flush=True)
        else:
            print(f"[NEO4J] Failed to store analysis", flush=True)
    except Exception as e:
        print(f"[NEO4J] Error storing analysis: {e}", flush=True)

NUM_BRANCHES = 4

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
    if not neo4j_auth:
        return JSONResponse({"error": "Neo4j not connected"}, status_code=503)
    result = await asyncio.to_thread(
        neo4j_query,
        "MATCH (h:Headline)-[:CAUSED*]->(p:Prediction) "
        "WITH h, p ORDER BY p.branch, p.depth "
        "WITH h, collect({text: p.text, agent: p.agent, confidence: p.confidence, "
        "branch: p.branch, depth: p.depth, timeframe: p.timeframe}) AS predictions "
        "RETURN h.text AS headline, h.created_at AS created_at, predictions "
        "ORDER BY h.created_at DESC",
    )
    if not result or result.get("error"):
        return JSONResponse({"error": "Query failed"}, status_code=500)
    fields = result["data"]["fields"]
    analyses = [
        dict(zip(fields, row))
        for row in result["data"]["values"]
    ]
    return JSONResponse(analyses)
