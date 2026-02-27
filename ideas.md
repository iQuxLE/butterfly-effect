# Butterfly Effect Machine - Ideas & Roadmap

## Current State (v0.1 - Hackathon MVP)
- 4 specialist agents analyze cascading consequences of a headline
- D3.js animated tree visualization
- SSE real-time streaming
- Ollama local inference (qwen3:8b)

---

## Immediate Fixes
- [ ] Fix node opacity — all nodes should be fully visible, not dimmed
- [ ] Make nodes clickable (expand full text, link to deeper analysis)

---

## Feature Ideas

### 1. Interactive Blog / Conversation Platform
- Each headline generates a "living blog post" about the cascading effects
- Users can **argue with the agents** — click a prediction and challenge it
- Agent responds with counter-arguments or updates its prediction
- Every ~10-20 min, an agent auto-generates a **summary of all conversations** happening across users
- Creates a living, evolving analysis that gets richer over time
- Think: Reddit meets AI analysts

### 2. Clickable Node Deep-Dives
- Click a prediction node → opens a detail panel / page
- If the question/topic was already explored by another user, **link to that existing thread**
- Shared knowledge graph across all users
- Nodes become a web of interconnected analyses

### 3. User-Deployable Agents
- Users can **spawn additional agents** to join the conversation
- Pick a specialty: "Military Analyst", "Climate Scientist", "Tech CEO", "Historian", etc.
- Custom agents can be configured with a persona prompt
- Agents debate each other in real-time threads
- Could become a marketplace of analyst perspectives

### 4. Financial Impact Agent ("What To Do With Your Money")
- **New agent: Financial Strategist**
- Given the cascading predictions, analyzes:
  - Which sectors/stocks go up or down
  - Index funds (S&P 500, NASDAQ, etc.)
  - Crypto impact (BTC, ETH, etc.)
  - Commodities (gold, oil, etc.)
  - Tech stocks specifically affected
  - Emerging market opportunities
- Output: a "Portfolio Impact Card" with directional arrows
- **CRITICAL DISCLAIMER**: "This is not investment advice. This is a prototype for educational/entertainment purposes only. Always do your own research and consult a financial advisor."

### 5. Polymarket / Prediction Market Integration
- Connect to Polymarket API to find **existing bets related to the cascading predictions**
- Show: "People are betting X% that this will happen"
- Could also suggest: "Based on this analysis, these prediction markets seem mispriced"
- Creates a bridge between AI analysis and real-money prediction markets
- Adds a "skin in the game" credibility layer

---

## Architecture Evolution

### v0.2 - Clickable Nodes + Financial Agent
- Add click handler to nodes → expand panel with full prediction
- Add 5th agent: Financial Strategist
- Add disclaimer component

### v0.3 - Conversation Mode
- Add chat interface per prediction node
- Users can argue with agents
- Agents update/defend predictions based on user input
- Store conversations (SQLite or similar)

### v0.4 - Living Blog
- Auto-summarize conversations every N minutes
- Public-facing blog view of trending headlines + analyses
- SEO-friendly pages per headline

### v0.5 - Multi-Agent Marketplace
- User-deployable custom agents
- Agent templates (presets for common specialties)
- Polymarket API integration
- Shared knowledge graph across headlines

---

## Tech Stack Evolution
- **Current**: FastAPI + Ollama + vanilla HTML/D3.js
- **Next**: Add SQLite for persistence, WebSockets for chat
- **Later**: React/Next.js frontend, PostgreSQL, Redis for real-time, Polymarket API

---

## Business Model Ideas (if this becomes a real product)
- Free tier: 5 headlines/day, basic agents
- Pro tier: unlimited headlines, custom agents, financial analysis, Polymarket data
- API access for developers
- White-label for newsrooms
