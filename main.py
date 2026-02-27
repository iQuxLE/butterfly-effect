import json
import re
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
import asyncio

app = FastAPI()

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "gemma3:latest"

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


def call_ollama(system_prompt, user_content):
    """Make a single Ollama API call and return parsed predictions."""
    with httpx.Client(timeout=120.0) as http_client:
        response = http_client.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content + "\n\n/no_think"},
                ],
                "stream": False,
                "options": {"temperature": 0.8, "num_predict": 1024},
            },
        )
        response.raise_for_status()
        text = response.json()["message"]["content"]
    return extract_json_array(text)


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
            call_ollama, agent["system"], f"NEWS HEADLINE: {headline}"
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

        for branch_idx in range(NUM_BRANCHES):
            chain = branches[branch_idx]
            if not chain:
                continue

            # Build context showing only THIS branch's causal chain
            context = f"NEWS HEADLINE: {headline}\n\n"
            context += "THE CAUSAL CHAIN SO FAR (each step caused the next):\n"
            for step_num, step in enumerate(chain, 1):
                context += f"  Step {step_num} [{step['agent']}]: {step['prediction']}\n"
            context += "\nPredict the NEXT domino in this specific chain."

            try:
                preds = await asyncio.to_thread(
                    call_ollama, agent["system"], context
                )
                pred = preds[0]  # We only want 1 prediction per branch

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

            except Exception as e:
                yield {"event": "error", "data": json.dumps({"agent_id": agent["id"], "branch": branch_idx, "error": str(e)})}

        yield {"event": "agent_done", "data": json.dumps({"agent_id": agent["id"]})}

    total = sum(len(b) for b in branches)
    yield {"event": "complete", "data": json.dumps({"total_predictions": total})}


@app.get("/")
async def root():
    return FileResponse("index.html")


@app.get("/analyze")
async def analyze(headline: str):
    return EventSourceResponse(generate_butterfly_effect(headline))
