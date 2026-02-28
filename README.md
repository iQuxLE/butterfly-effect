#  Butterfly Effect Machine

## Origin Story

This project was born from a hackathon brainstorming session (Feb 2026). We were looking for an agentic AI project that:
- Could be built in under 2 hours
- Had a visually impressive, demo-friendly output
- Connected to current real-world trends (DOGE, tariff rulings, AI-generated ads, GEO)
- Was genuinely novel — not already done

The winning concept: **a tool where you enter any news headline and a chain of specialist AI agents predict cascading consequences, visualized as a live-growing tree**. The "butterfly effect" — one headline, many dominoes.

The idea draws on February 2026 context: the Supreme Court striking down Trump's tariffs, DOGE cutting 20% of federal workers, Svedka's universally-hated AI Super Bowl ad, and the rise of Generative Engine Optimization (GEO). All topics where cascading second/third-order effects matter more than the headline itself.

---

## What It Does

1. User enters a news headline (or picks from examples)
2. 4 AI agents analyze it using a **per-branch causal chain** architecture:
   - **Economist** (teal `#4ecdc4`) — immediate market/trade consequences (days)
   - **Geopolitical Strategist** (red `#ff6b6b`) — international reactions (weeks)
   - **Social Analyst** (yellow `#ffd93d`) — domestic/cultural impact (months)
   - **Futurist** (purple `#c084fc`) — long-term paradigm shifts (1-5 years)
3. The Economist produces 4 distinct predictions, creating 4 independent branches
4. Each subsequent agent is called **once per branch**, seeing only that branch's causal chain
5. Results stream in real-time via SSE as an **animated D3.js tree** that grows node by node
6. Each node is **clickable** — opens a detail panel with full text, confidence level, timeframe, and the causal chain from headline to that prediction
7. Each branch has a **consistent color** from top to bottom (teal, red, yellow, purple)
8. Rows are ordered by **time horizon**: days → weeks → months → 1-5 years

---

## Project Structure

```
butterfly-effect-machine/
├── main.py          # FastAPI backend — agent orchestration + SSE streaming
├── index.html       # Single-file frontend — D3.js tree + detail panel + all CSS/JS
├── ideas.md         # Feature roadmap and future vision
└── CLAUDE.md        # This file
```

**Total: 2 files of actual code.** No build step, no npm, no bundler.

---

## Architecture

### Per-Branch Causal Chain Design

The core architectural insight: each branch is an **independent causal chain**. The Economist creates the initial fan-out (4 predictions = 4 branches). Every subsequent agent is called **once per branch** with only that branch's accumulated context. This means:

- **Economist**: 1 Ollama call → 4 predictions (creates 4 branches)
- **Geopolitical Strategist**: 4 Ollama calls, each receives 1 Economist prediction → 1 prediction each
- **Social Analyst**: 4 Ollama calls, each receives a chain of Economist → Geopolitics → 1 prediction each
- **Futurist**: 4 Ollama calls, each receives full chain → 1 prediction each

**Total: 13 Ollama API calls per analysis** (1 + 4 + 4 + 4).

This creates 4 genuinely independent causal stories, each flowing top to bottom through all 4 time horizons.

### Data Flow

```
[Browser]                           [FastAPI Backend]                    [Ollama]
   |                                      |                                |
   |-- GET /analyze?headline=...  ------->|                                |
   |                                      |-- POST /api/chat (Economist) ->|
   |                                      |<-- JSON: 4 predictions ------- |
   |<-- SSE: agent_start ---------------- |                                |
   |<-- SSE: prediction (x4, branch 0-3)  |                                |
   |<-- SSE: agent_done ----------------- |                                |
   |                                      |                                |
   |                                      |-- POST /api/chat (Geo, br 0) ->|
   |                                      |<-- JSON: 1 prediction -------- |
   |<-- SSE: agent_start ---------------- |                                |
   |<-- SSE: prediction (branch 0) ------ |                                |
   |                                      |-- POST /api/chat (Geo, br 1) ->|
   |<-- SSE: prediction (branch 1) ------ |                                |
   |                                      |-- POST /api/chat (Geo, br 2) ->|
   |<-- SSE: prediction (branch 2) ------ |                                |
   |                                      |-- POST /api/chat (Geo, br 3) ->|
   |<-- SSE: prediction (branch 3) ------ |                                |
   |<-- SSE: agent_done ----------------- |                                |
   |                                      |   ... (Social, Futurist) ...   |
   |<-- SSE: complete ------------------- |                                |
```

### SSE Event Types

| Event | Payload | Purpose |
|-------|---------|---------|
| `start` | `{headline}` | Analysis begun |
| `agent_start` | `{agent_id, agent_name, color, icon}` | Agent is thinking — UI shows spinner |
| `prediction` | `{agent_id, agent_name, color, icon, prediction, timeframe, confidence, branch, depth}` | A single prediction — add node to tree |
| `agent_done` | `{agent_id}` | Agent finished — UI marks chip as done |
| `error` | `{agent_id, error}` or `{agent_id, branch, error}` | Agent failed (JSON parse error, timeout) |
| `complete` | `{total_predictions}` | All agents done — close SSE |

**Key fields in `prediction` events:**
- `branch` (int, 0-3): Which of the 4 independent branches this prediction belongs to
- `depth` (int, 0-3): The time-horizon row (0=days/Economist, 1=weeks/Geopolitics, 2=months/Social, 3=years/Futurist)
- `timeframe` (string): Human-readable label from the agent's `timeframe_label` field

### Agent Orchestration (main.py)

Each agent is defined as a dict with `id`, `name`, `icon`, `color`, `timeframe_label`, and `system` (prompt). The `generate_butterfly_effect()` async generator:

1. **Step 1 — Economist (fan-out)**: Makes 1 Ollama call, gets `NUM_BRANCHES` (4) predictions. Each prediction becomes branch 0, 1, 2, 3. Stored in `branches[i]` (a list of lists tracking each branch's causal chain).

2. **Step 2 — Subsequent agents (per-branch)**: For each of the 3 remaining agents, iterates over all 4 branches. For each branch, builds a context string containing ONLY that branch's causal chain so far, then makes 1 Ollama call to get 1 prediction. Appends to that branch's chain.

**Context building for per-branch calls:**
```
NEWS HEADLINE: {headline}

THE CAUSAL CHAIN SO FAR (each step caused the next):
  Step 1 [Economist]: {prediction from branch N}
  Step 2 [Geopolitical Strategist]: {prediction from branch N}

Predict the NEXT domino in this specific chain.
```

Each agent's system prompt is calibrated for this:
- Economist: "predict exactly 4 distinct immediate economic consequences"
- Others: "predict exactly 1 [type] consequence that follows FROM THIS SPECIFIC [chain]"

### LLM Integration (Ollama)

- **Model**: `qwen3:8b` — good JSON output, fast on Apple Silicon
- **Endpoint**: `http://localhost:11434/api/chat`
- **Settings**: `temperature: 0.8`, `num_predict: 1024`
- **Thinking mode**: Disabled via `/no_think` appended to user message (qwen3-specific)
- **Timeout**: 120 seconds per call
- **Total calls per analysis**: 13 (1 Economist + 4 Geopolitics + 4 Social + 4 Futurist)

**To swap to a different provider**, only `call_ollama()` needs to change. The rest of the system is provider-agnostic — it just expects a list of `{prediction, confidence}` dicts back.

#### Swapping to OpenAI
```python
from openai import OpenAI
client = OpenAI()

def call_ollama(system_prompt, user_content):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.8,
    )
    text = response.choices[0].message.content
    return extract_json_array(text)
```

#### Swapping to Anthropic Claude
```python
import anthropic
client = anthropic.Anthropic()  # needs ANTHROPIC_API_KEY env var

def call_ollama(system_prompt, user_content):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text
    return extract_json_array(text)
```

### Frontend (index.html)

Everything in a single HTML file (~656 lines) — no build, no framework.

**Libraries loaded from CDN:**
- D3.js v7 (`https://d3js.org/d3.v7.min.js`) — tree layout + SVG rendering
- Google Fonts Inter — typography

**Components:**

1. **Input Area** — text input + "Trace the Ripples" button + example headline chips
2. **Agent Status Bar** — 4 chips (Economist, Geopolitical Strategist, Social Analyst, Futurist) that light up/pulse when active, dim when done
3. **Headline Display** — shows the current headline in stylized quotes
4. **Tree Visualization** (SVG) — D3 tree layout, animated node entry, glow filter on circles
5. **Detail Panel** — slide-in right panel (420px) with full prediction text, agent badge, timeframe, confidence, and causal chain
6. **Overlay** — dark backdrop when panel is open

**Tree Rendering (`renderTree()`):**
- Uses D3's `d3.hierarchy()` + `d3.tree()` layout
- Enter/Update/Exit pattern for both links (paths) and nodes (groups)
- Nodes enter with `opacity: 0` and transition to `1`
- Links use `d3.linkVertical()` for smooth curves
- SVG glow filters (`feGaussianBlur` + `feMerge`): `#glow` (stdDeviation 4) on all circles, `#glow-strong` (stdDeviation 8) on hover
- Called every time a new prediction arrives — tree re-layouts smoothly
- `g` element is centered at `translate(${width / 2}, 50)`, nodes use `offsetX = -(width / 2 - 100)` for proper positioning

**Branch Tracking (`branchLeaf{}`):**

The frontend uses a `branchLeaf` dictionary to track the current leaf node of each branch. This is the key mechanism for building the tree correctly:

```javascript
const branchLeaf = {};  // {branchIndex: currentLeafNode}

// When a prediction arrives:
if (data.depth === 0) {
    // Economist: attach directly to root, register as branch leaf
    treeData.children.push(newNode);
    branchLeaf[branchIdx] = newNode;
} else {
    // Subsequent agents: attach to current leaf of this branch, update leaf
    const parent = branchLeaf[branchIdx];
    parent.children.push(newNode);
    branchLeaf[branchIdx] = newNode;
}
```

This ensures each branch grows as a single chain: root → economist → geopolitics → social → futurist.

**Tree Data Structure:**
```javascript
treeData = {
  id: 0,
  label: "Headline text...",
  fullText: "Full headline",
  color: "#fff",
  branchColor: "#fff",
  icon: "🦋",
  isRoot: true,
  children: [
    {
      id: 1,
      label: "Economic prediction...",
      fullText: "Full prediction text",
      timeframe: "days",
      confidence: "high",
      color: "#4ecdc4",       // agent color (used for fill at 20% opacity)
      branchColor: "#4ecdc4", // branch color (used for stroke + link)
      icon: "📊",
      agentName: "Economist",
      children: [
        {
          // geopolitics prediction
          color: "#ff6b6b",       // agent color (geopolitics)
          branchColor: "#4ecdc4", // SAME branch color (teal throughout)
          children: [
            {
              // social prediction
              color: "#ffd93d",       // agent color (social)
              branchColor: "#4ecdc4", // SAME branch color
              children: [
                {
                  // futurist prediction
                  color: "#c084fc",       // agent color (futurist)
                  branchColor: "#4ecdc4", // SAME branch color
                  children: []
                }
              ]
            }
          ]
        }
      ]
    },
    // ... 3 more branches (red, yellow, purple branchColor)
  ]
}
```

**Node Coloring (dual-color system):**
- `color` = the **agent's** color (varies by depth/row). Used for circle `fill` at 20% opacity.
- `branchColor` = the **branch's** color (consistent top to bottom). Used for circle `stroke` and link `stroke`.
- This creates the visual effect: each branch is a consistent color line, but each row subtly shows the agent type through the fill.

---

## Color System

### Branch Colors (consistent per vertical line)
| Branch Index | Color | Hex |
|-------------|-------|-----|
| 0 | Teal | `#4ecdc4` |
| 1 | Red | `#ff6b6b` |
| 2 | Yellow | `#ffd93d` |
| 3 | Purple | `#c084fc` |

### Agent Colors (per row/depth)
| Agent | Color | Hex | Depth |
|-------|-------|-----|-------|
| Economist | Teal | `#4ecdc4` | 0 (days) |
| Geopolitical Strategist | Red | `#ff6b6b` | 1 (weeks) |
| Social Analyst | Yellow | `#ffd93d` | 2 (months) |
| Futurist | Purple | `#c084fc` | 3 (1-5 years) |
| Root (Headline) | White | `#ffffff` | — |

### Confidence Badges
- High → teal (`#4ecdc4`)
- Medium → yellow (`#ffd93d`)
- Low → red (`#ff6b6b`)

### Background
`#0a0a0f` with subtle radial gradients using teal, red, and purple at 6% opacity.

---

## Known Issues & Bugs

### 1. LLM JSON Parsing Fragility
Despite `extract_json_array()` being fairly robust, local models (especially qwen3 with thinking mode) sometimes produce malformed JSON. The `/no_think` suffix helps but isn't 100% reliable. Cloud APIs (OpenAI, Claude) are much more reliable for structured output.

### 2. Occasional Missing Branches
If the Economist returns fewer than `NUM_BRANCHES` predictions, some branches will be empty. The code handles this with `preds[:NUM_BRANCHES]` truncation and `if not chain: continue` guards, but the tree will have fewer than 4 branches in that case.

### 3. Node Label Overlap at Narrow Widths
The D3 tree layout distributes nodes based on container width. On narrow screens, node labels can overlap. The `separation()` config (`1.8` same parent, `2.2` different parent) helps but isn't perfect below ~1000px.

---

## Running the Project

### Prerequisites
- Python 3.11+
- Ollama installed and running (`brew install ollama && ollama serve`)
- A model pulled: `ollama pull qwen3:8b` (or any model — change `MODEL` in main.py)

### Install & Run
```bash
cd butterfly-effect-machine

# Install Python dependencies
pip install fastapi uvicorn httpx sse-starlette

# Start Ollama (if not running)
ollama serve &

# Start the app
python -m uvicorn main:app --host 0.0.0.0 --port 8888

# Open browser
open http://localhost:8888
```

### Available Ollama Models (tested)
| Model | Speed | JSON Quality | Notes |
|-------|-------|-------------|-------|
| `qwen3:8b` | Fast | Good | Default. Use `/no_think` to disable thinking mode |
| `llama3.1:8b` | Fast | Good | Reliable JSON output |
| `gemma3:12b` | Medium | Very good | Best quality but slower |
| `mistral:7b` | Fast | OK | Sometimes wraps JSON in markdown |

### Configuration
In `main.py`, these constants control behavior:
- `OLLAMA_URL` — Ollama endpoint (default: `http://localhost:11434/api/chat`)
- `MODEL` — which Ollama model to use (default: `qwen3:8b`)
- `NUM_BRANCHES` — number of branches/initial predictions (default: 4)

---

## Design Decisions & Trade-offs

### Why per-branch agent calls (not shared context)?
The v0.1 architecture had all agents see ALL prior predictions. This produced a "wishy washy" tree where branches weren't causally connected — the Geopolitical Strategist would give 4 predictions that mixed context from all 4 Economist predictions. By calling each agent once per branch with only that branch's chain, each branch tells a coherent causal story. The trade-off is 13 Ollama calls instead of 4, but the quality improvement is significant.

### Why 4 branches?
Each branch corresponds to one of the 4 agents, giving each agent a "home" branch color. This makes the tree visually balanced (4 vertical lines, 4 depth levels = 16 prediction nodes + 1 root).

### Why SSE instead of WebSockets?
SSE is simpler (one-way server→client), works over standard HTTP, and is perfect for this use case where the client only sends one request and receives a stream of updates. WebSockets would be needed for the future conversation/chat features.

### Why a single HTML file?
Speed. No build step, no node_modules, instant iteration. For a hackathon prototype this is ideal. The file is ~656 lines but well-structured. For production, split into components with a framework.

### Why Ollama (not a cloud API)?
The user didn't have an Anthropic API key available, and the Claude subscription doesn't include API access. Ollama is free, local, and works offline. The architecture is provider-agnostic — swapping to OpenAI/Claude/Gemini only changes the `call_ollama()` function.

### Why D3.js for the tree?
D3's tree layout is the gold standard for hierarchical visualizations. The enter/update/exit pattern allows smooth incremental rendering as predictions arrive. The SVG glow filter creates the distinctive dark-mode aesthetic. Alternatives considered: vis.js (overkill), CSS-only tree (limited), canvas (harder to make interactive).

---

## Future Vision (see ideas.md for full roadmap)

### v0.2 — Financial Strategist Agent
- Add 5th agent: Financial Strategist (stocks, crypto, commodities impact)
- Disclaimer: "Not investment advice"

### v0.3 — Interactive Conversations
- Click a node → argue with the agent that made the prediction
- Agent defends or updates its prediction based on user challenge
- WebSocket upgrade for real-time chat

### v0.4 — Living Blog
- Auto-summarize all conversations every 10-20 minutes
- Public blog pages per headline
- Shared knowledge graph — if a topic was already analyzed, link to it

### v0.5 — Agent Marketplace + Polymarket
- Users deploy custom agents (Military Analyst, Climate Scientist, etc.)
- Connect to Polymarket API for prediction market data
- "People are betting X% this will happen"

---

## Agent Prompt Engineering Notes

The Economist prompt is different from the others:
- **Economist**: "predict exactly {NUM_BRANCHES} distinct immediate economic consequences" — returns a JSON array with 4 items
- **All others**: "predict exactly 1 [type] consequence that follows FROM THIS SPECIFIC [chain]" — returns a JSON array with 1 item

Each agent's system prompt follows a strict pattern:
1. **Role declaration**: "You are a [role]"
2. **Context instruction**: "You are given a news headline and a SPECIFIC [chain context]..."
3. **Scope constraint**: "predict exactly 1 [type] consequence ([timeframe])"
4. **Quality instruction**: "Be specific, bold, and concise. 1-2 sentences max."
5. **Output format**: 'Return ONLY a JSON array: [{"prediction": "...", "confidence": "high/medium/low"}]'

The output format instruction is critical. Local models need very explicit "Return ONLY a JSON array, no other text" to avoid wrapping in explanations. Cloud models (Claude, GPT-4o) are more reliable but still benefit from explicit formatting.

The `confidence` field (high/medium/low) is agent-determined and displayed as color-coded badges in the UI. It adds perceived rigor even though it's subjective.

Each agent also has a `timeframe_label` field (string) that is sent with each SSE prediction event and displayed below nodes in the tree:
- Economist: `"days"`
- Geopolitical Strategist: `"weeks"`
- Social Analyst: `"months"`
- Futurist: `"1-5 years"`

---

## Key Code Patterns

### Robust JSON Extraction from LLMs
```python
def extract_json_array(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)  # qwen3 thinking
    text = re.sub(r'```json\s*', '', text)  # markdown fences
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    match = re.search(r'\[.*\]', text, flags=re.DOTALL)  # find array
    if match:
        raw = re.sub(r'\*\*', '', match.group(0))  # strip bold markers
        arr = json.loads(raw)
        for item in arr:
            if "prediction" in item:
                item["prediction"] = re.sub(r'\*\*', '', item["prediction"])
        return arr
    raise ValueError(f"No JSON array found")
```

### Per-Branch Context Building
```python
# For agents after the Economist:
context = f"NEWS HEADLINE: {headline}\n\n"
context += "THE CAUSAL CHAIN SO FAR (each step caused the next):\n"
for step_num, step in enumerate(chain, 1):
    context += f"  Step {step_num} [{step['agent']}]: {step['prediction']}\n"
context += "\nPredict the NEXT domino in this specific chain."
```

### Branch Leaf Tracking (Frontend)
```javascript
const branchLeaf = {};  // {branchIndex: currentLeafNode}

// depth 0: attach to root, register as leaf
if (data.depth === 0) {
    treeData.children.push(newNode);
    branchLeaf[branchIdx] = newNode;
} else {
    // depth 1+: attach to current leaf, update leaf pointer
    const parent = branchLeaf[branchIdx];
    parent.children.push(newNode);
    branchLeaf[branchIdx] = newNode;
}
```

### D3 Enter/Update/Exit for Incremental Tree
```javascript
const nodes = g.selectAll('.node-group').data(nodeData, d => d.data.id);

const enter = nodes.enter().append('g')
  .attr('class', 'node-group')
  .style('opacity', 0)
  .on('click', (event, d) => { event.stopPropagation(); openPanel(d.data); });

enter.append('circle')
  .attr('fill', d => d.data.color || '#fff')        // agent color
  .attr('stroke', d => d.data.branchColor || '#fff') // branch color
  .attr('fill-opacity', 0.2)
  .attr('filter', 'url(#glow)');

enter.transition().duration(500).style('opacity', 1);

nodes.transition().duration(400)
  .attr('transform', d => `translate(${d.x + offsetX}, ${d.y})`);

nodes.exit().remove();
```

### SSE Client Pattern
```javascript
const evtSource = new EventSource(`/analyze?headline=${encodeURIComponent(headline)}`);

evtSource.addEventListener('prediction', (e) => {
  const data = JSON.parse(e.data);
  const branchIdx = data.branch;
  const branchColor = BRANCH_COLORS[branchIdx];
  // Build node with both agent color and branch color, attach to tree
});

evtSource.addEventListener('complete', () => evtSource.close());
```

---

## Development History

### v0.1 — Initial Hackathon MVP
- 4 agents, shared context (all agents see all prior predictions)
- 3 branches, 4 Ollama calls total
- Round-robin node distribution to branches
- Bug: tree was "wishy washy" — branches weren't causally connected

### v0.2 — Per-Branch Architecture (current)
- Rewrote backend to call agents once per branch
- 4 branches, 13 Ollama calls total
- Each branch is an independent causal chain
- Added `branch` and `depth` fields to SSE events
- Frontend uses `branchLeaf{}` tracking instead of round-robin
- Dual-color system: agent color (fill) + branch color (stroke/links)
- Clickable nodes with slide-in detail panel showing causal chain
- Fixed: branches now have consistent colors top to bottom
- Fixed: rows ordered by time horizon (days → weeks → months → years)
