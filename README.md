# 🤖 Agentic RAG System - A Production System.

> ⚠️ **Please don't treat this like a `.gitignore`!** Every section has something cool, I promise.

A production-grade **Retrieval-Augmented Generation** system built with **LangGraph**, featuring multi-tenant isolation, intelligent caching, rate limiting, generator-evaluator and human-in-the-loop workflows. Deployed on AWS with high availability architecture.

> *Because `ctrl+F` in a 50-page PDF isn't a personality trait.* 📄🔍

**🌐 Test it Right here:** [mlinterviewnotes.com](https://mlinterviewnotes.com) 
<br>
**Quests to do:**
- Click on the name of any pdf, Surprise awaiting - Atleast I felt like the explorer.
- Select a source and ask an irrelevant question see what happens
- Just ask a simpleton see how the LLM reacts 
- Ask same question on different tenants - Will the same items be retrieved ? Will you get a cached response ?



**🎁 Even the users are created for you:** See `data/Users_and_Question_Bank.xlsx` for test credentials

---

## 🏗️ Architecture Overview
<p align="center">
  <img src="images/architecture.png" alt="Main Agent Graph" width="700"/>
</p>



The system implements a **ReAct (Reasoning + Acting)** pattern where the agent iteratively reasons about user queries and selects appropriate tools until the task is complete.

### 🧱 Key Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| 🎯 **Agent Orchestration** | LangGraph | State machine for multi-step reasoning |
| 🔍 **Vector Store** | Qdrant Cloud | Semantic search with RBAC filtering |
| 🗄️ **Database** | PostgreSQL (RDS) | Conversation persistence, checkpointing |
| ⚡ **Cache** | Redis (ElastiCache) | Semantic caching, rate limiting |
| 🧠 **LLM** | GPT-4o-mini | Reasoning and generation |
| 📐 **Embeddings** | text-embedding-3-small | Document & query embeddings |
| 🎖️ **Reranking** | Cohere Rerank | Result relevance optimization |

---

## ✨ Features

### 1. 🛠️ Multi-Agent Tool System

*"One agent to rule them all, seven tools to help it to achieve things."* 💍
<p align="center">
  <img src="images/main_agent_graph.png" alt="Main Agent Graph" width="700"/>
</p>

The agent has access to **7 specialized tools**, each designed for specific tasks:

```
┌─────────────────────────────────────────────────────────────────┐
│                        AVAILABLE TOOLS                          │
├─────────────────┬───────────────────────────────────────────────┤
│ calculator      │ Safe math evaluation (sqrt, log, trig, etc.)  │
│ expense_manager │ Track expenses by category with CRUD ops      │
│ rag_retriever   │ Semantic search with visibility filtering     │
│ general_llm     │ General knowledge questions                   │
│ twitter_gen     │ Generate tweets with self-critique loop       │
│ linkedin_gen    │ Professional posts with outline generation    │
│ doc_embedder    │ Process PDFs/arXiv papers into knowledge base │
└─────────────────┴───────────────────────────────────────────────┘
```

---

### 2. 🔄 Sub-Graphs for Complex Workflows

Each complex tool is implemented as a **sub-graph** with its own state machine, enabling sophisticated multi-step workflows.

#### 🐦 Twitter Generation Sub-Graph

<table>
<tr>
<td width="50%" valign="top">

**Self-Critique Loop:**
- Generate draft tweet (max 280 chars)
- AI critic evaluates quality (1-10 score)
- Iterate until quality >= 8.0 or max 3 iterations
- Human approval via interrupt before posting

**Approval Loop:**

<img src="images/caching_2.png" alt="Semantic Caching" width="650"/>

</td>
<td width="50%">
<img src="images/twitter_subgraph.png" alt="Twitter Sub-Graph" width="400" height="480"/>
</td>
</tr>
</table>

#### 💼 LinkedIn Post Sub-Graph

<table>
<tr>
<td width="50%" valign="top">

**Two-Stage Generation:**
1. **Outline Creation:** Hook, main points, evidence, CTA
2. **Full Post Generation:** Expand outline with storytelling
3. **Quality Evaluation:** Iterate with self-critique
4. **Finalization:** Format for platform

**Human-in-the-Loop (HITL):**

<img src="images/Human_in_the_loop.png" alt="Human in the Loop" width="650"/>

</td>
<td width="50%">
<img src="images/linkedIn_subgraph.png" alt="LinkedIn Sub-Graph" width="400" height="600"/>
</td>
</tr>
</table>

#### 📄 Document Embedder Sub-Graph

<table>
<tr>
<td width="50%" valign="top">

**Processing Pipeline:**
1. arXiv detection and paper fetching
2. Duplicate check against existing documents
3. PDF chunking with parallel processing (8 workers)
4. Vector embedding and Qdrant storage
5. Blog post generation (parallel)[Not-Implemented]
6. S3 upload for web hosting[Not-Implemented]

</td>
<td width="50%">
<img src="images/embedder_subgraph.png" alt="Embedder Sub-Graph" width="400" height="400"/>
</td>
</tr>
</table>

---

### 3. 👨‍💻 Human-in-the-Loop (HITL)

*"Because even AI needs adult supervision sometimes."* 👀

The system uses LangGraph's `interrupt()` to pause execution at critical decision points:

```python
# Tweet approval interrupt
approval = interrupt({
    "type": "tweet_approval",
    "draft": state["draft"],
    "quality_score": state["quality_score"],
    "iterations": state["iteration_count"]
})
```

**How it works:**
1. Agent generates content and reaches approval checkpoint
2. Execution pauses, state persisted to PostgreSQL
3. User reviews content in frontend
4. On approval, `Command(resume={...})` continues execution
5. Content is finalized and returned

---

### 4. 🧠 Semantic Caching (Tenant-Level)

The system implements intelligent caching that isolates data by tenant while using semantic similarity to serve cached responses for similar questions.

<table>
<tr>
<td width="50%" valign="top">

**User A asks a question:**

A user from tenant `hpiq` in the `physics` department asks about "human in the loop". The response is generated and cached with tenant context.

<img src="images/cache_hp-a.png" alt="Cache Miss - First Query" width="650" height="400"/>

</td>
<td width="50%" valign="top">

**User B asks similar question:**

Another user from the **same tenant** asks a semantically similar question. The system finds a cached response with cosine similarity >= 0.75 and returns it instantly.

<img src="images/cache_hp-b.png" alt="Cache Hit - Similar Query" width="650" height="400"/>

</td>
</tr>
</table>

<table>
<tr>
<td width="50%" valign="top">
<br>
<br>
<br>
<br>
<br>
<br>

**User C from DIFFERENT tenant asks same question:**

A user from tenant `together` (different from `hpiq`) asks the same question. Despite semantic similarity, the cache is **not used** because tenant IDs don't match. A fresh response is generated.

This ensures **data isolation** - tenants never see each other's cached responses.

</td>
<td width="50%">
<img src="images/cache-c.png" alt="Cache Miss - Different Tenant" width="650" height="400"/>
</td>
</tr>
</table>

<table>
<tr>
<td width="50%" valign="top">

**Two-Tier Cache Strategy:**

| Tier | Method | Threshold |
|------|--------|-----------|
| **Exact Match** | SHA-256 hash of query | 100% match |
| **Semantic Match** | Cosine similarity of embeddings | >= 0.75 |

**Intelligent Cache Rules:**
- RAG responses: Cache if tenant AND department match
- Non-RAG responses: Cache if tenant matches
- LRU eviction: Max 25 entries per tenant

</td>
<td width="50%" valign="top">

**Tenant Isolation:**
```
Cache Key: chat_cache:{tenant_id}:{question_hash}
Index Key: cache_embedding_index:{tenant_id}
```

Each tenant has isolated cache storage. Queries are only matched against cache entries from the same tenant, ensuring complete data privacy between organizations.

</td>
</tr>
</table>

---

### 5. 🚦 Rate Limiting

*"Yes, we handle the `429` so you don't have to rage-quit."* 😤

<p align="center">
  <img src="images/token_rate_limit.png" alt="Token Rate Limit" width="700"/>
</p>

**User Tier System:**

| Tier | Requests/min | Tokens/min |
|------|--------------|------------|
| `free` | 3 | 100 |
| `power` | 30 | 20,000 |
| `super` | Unlimited | Unlimited |
> Feel free to create a free account and test the rate-limiting stuff out.
**Implementation:**
- 📊 **Sliding Window Algorithm** with Redis
- 🌍 **Global System Limit:** 400 requests/min
- ⏱️ **Exponential Backoff:** 1s → 2s → 4s → 8s → 16s (capped at 30s)

---

### 6. 📬 Request Queuing

When system is at capacity, requests enter a Redis-backed queue:

```
┌─────────────────────────────────────────────────────────┐
│                    REQUEST QUEUE                        │
├─────────────────────────────────────────────────────────┤
│  Max Queue Size: 100 items                              │
│  Max Wait Time: 60 seconds                              │
│  Stale Cleanup: Automatic (client disconnects)          │
└─────────────────────────────────────────────────────────┘
```

**SSE Queue Updates:**
```json
{"event": "queue", "data": {"position": 3, "estimated_wait": "15s"}}
```

---

### 7. 🔐 RBAC & Multi-Tenant Filtering

*"Your data is yours. Their data is theirs. We don't mix drinks."* 🍸

**How Multi-Tenancy Works:**

- 🏢 **Tenant Isolation:** Each organization lives in its own bubble. No peeking at neighbors!
- 🏬 **Department Filtering:** Physics folks see physics papers. HR sees... well, HR stuff.
- 🔒 **Private Documents:** Upload something private? Only YOU can see it. Not even other users in your tenant.
- 👀 **Public Documents:** Share with your tenant + department. Sharing is caring (within limits).

**The Magic Formula:**
```
Can I see this document? =
  (Is it public? AND same tenant? AND same department?)
  OR
  (Is it private? AND did I upload it?)
```

*Plot twist: Even if you guess the document ID, the filter says "nice try" and shows you nothing.* 

---

### 8. 🧩 Memory & State Management

**PostgreSQL Checkpointing:**
- Conversation history persists across server restarts
- Thread-based state isolation
- LangGraph's `PostgresSaver` for reliable checkpoints

**Context Variables (Thread-Safe):**
```python
current_thread_id = contextvars.ContextVar("thread_id")
current_user_id = contextvars.ContextVar("user_id")
current_tenant_id = contextvars.ContextVar("tenant_id")
current_department = contextvars.ContextVar("department")
```

**Recursion & Loop Limits:**

| Limit | Value | Purpose |
|-------|-------|---------|
| Agent Timeout | 120 seconds | Prevent runaway executions |
| Tweet Iterations | 3 max | Self-critique loop cap |
| LinkedIn Iterations | 3 max | Quality refinement cap |
| Queue Wait | 60 seconds | Request timeout |

---

### 9. 🔭 Observability with LangSmith

*"Because `print('here')` debugging doesn't scale."* 🐛

<table>
<tr>
<td width="50%">
<img src="images/langsmith_1.png" alt="LangSmith Tracing 1" width="125%"/>
</td>
<td width="50%">
<img src="images/langsmith_2.png" alt="LangSmith Tracing 2" width="100%"/>
</td>
</tr>
</table>

**Tracing Configuration:**
- Every LLM call tagged with `run_name` for easy filtering
- Metadata includes: `user_id`, `tenant_id`, `thread_id`, `department`
- Tags: `tenant:{id}`, `user:{id}`, `rag:true/false`, `streaming:true`

**Traced Operations:**
- `react_agent_reasoning` - Main agent decisions
- `twitter_draft_generation` / `twitter_critique`
- `linkedin_outline_generation` / `linkedin_post_generation`
- `rag_retrieval` - Document search queries

---

## ☁️ Deployment

**AWS Services:**
- **EC2:** Compute-optimized instances for parallel PDF processing
- **RDS PostgreSQL:** Multi-AZ for conversation persistence
- **ElastiCache Redis:** Caching and rate limiting
- **ALB:** HTTPS termination with 300s timeout for SSE streaming
- **ACM:** SSL certificate management

---

## 🧰 Tech Stack

```
Backend:
├── FastAPI (async API framework)
├── LangGraph (agent orchestration)
├── LangChain (LLM integrations)
├── PostgreSQL  (persistence)
├── Redis (caching, rate limiting)
├── Qdrant (vector search)
├── Cohere (reranking)
└── Unstructured (PDF processing)

Frontend:
├── React
├── TypeScript
└── Vite

Infrastructure:
├── AWS (EC2, RDS, ElastiCache, ALB, S3)
├── nginx (reverse proxy)
├── systemd (service management)
└── LangSmith (observability)
```

---

## 🔌 API Endpoints
> /v1/ I am kinda impressed with myslef, towards growth

**🔐 Authentication**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/signup` | POST | Create new account |
| `/api/v1/auth/signin` | POST | Login & get token |
| `/api/v1/auth/me/{user_id}` | GET | Get user profile |

**💬 Chat & Conversations**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/chat/stream` | POST | SSE streaming chat with agent |
| `/api/v1/chat/stream-with-file` | POST | Chat with PDF upload |
| `/api/v1/chat/{thread_id}/approve` | POST | HITL approval endpoint |
| `/api/v1/chat/{thread_id}/history` | GET | Retrieve conversation |
| `/api/v1/chat/conversations` | GET | List all conversations |
| `/api/v1/chat/conversations/{thread_id}` | DELETE | Delete a conversation |

**📄 Document & Knowledge Base**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/embed-house/upload` | POST | Upload document for embedding |
| `/api/v1/embed-house/job/{job_id}` | GET | Check embedding job status |
| `/api/v1/embed-house/knowledge-base/sources` | GET | List all uploaded documents |
| `/api/v1/embed-house/knowledge-base/document/{id}` | DELETE | Remove document |

**📊 Stats & Monitoring**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service health check |
| `/api/v1/chat/usage/stats` | GET | Rate limit usage stats |
| `/api/v1/chat/cache/stats` | GET | Cache hit/miss stats |

---

## ⚡ Performance Characteristics

| Metric | Value |
|--------|-------|
| Parallel PDF Workers | 8 (large) / 4 (medium) |
| Embedding Model | text-embedding-3-small |
| Vector Dimensions | 1536 |
| Cache Hit Ratio | ~40% (semantic matching) |
| Avg Response Time | < 2s (cached) / 5-10s (RAG) |
| Concurrent Users | ~50-100 per instance |

---

## 💰 Cost Analysis

*"Because 'it depends' isn't a budget."* 🧮

### 🏗️ Infrastructure Costs (Fixed Monthly)

| Component | Specification | Monthly Cost |
|-----------|---------------|--------------|
| 🖥️ **EC2** (2x c6i.2xlarge) | 8 vCPU, 16 GB RAM each | $490 |
| 🐘 **RDS PostgreSQL** | db.r6g.large, Multi-AZ | $320 |
| ⚡ **ElastiCache Redis** | cache.r6g.large + replica | $390 |
| ⚖️ **ALB** | + LCU charges | $30 |
| 🌐 **NAT Gateways** (2x) | + data processing | $70 |
| 🛤️ **Route 53 + ACM** | Hosted zone + queries | $2 |
| 📤 **Data Transfer** | ~50GB outbound | $5 |
| 🔐 **Secrets Manager** | 5 secrets | $2 |
| **Total Infrastructure** | | **$1,309/month** |

> *With Reserved Instances (1-year): ~$850/month (35% savings)*

---

### 📊 Usage Pattern Per User

| Metric | Value |
|--------|-------|
| 📨 Requests per hour | 25 |
| ⏰ Active hours per day | 6 |
| 📅 Active days per month | 22 (workdays) |
| 📝 Average input tokens | 250 |
| 📄 Average output tokens | 1,000 |
| 📁 Document uploads per hour | 1 |
| 📖 Average document size | 10 pages |
| 🔍 RAG hits per hour | 15 |
| ✅ Cache hit rate | 20% |

---

### 🔢 Token Calculations Per User Per Month

```
Monthly Active Hours = 6 hrs × 22 days = 132 hours
Monthly Requests = 25 req/hr × 132 hrs = 3,300 requests
Uncached Requests = 3,300 × 80% = 2,640 requests

📥 Input Tokens (GPT-4o-mini)
   2,640 requests × 250 tokens = 660,000 tokens
   Cost: 660K × $0.00015/1K = $0.10

📤 Output Tokens (GPT-4o-mini)
   2,640 requests × 1,000 tokens = 2,640,000 tokens
   Cost: 2.64M × $0.0006/1K = $1.58

🔍 RAG Queries (Embeddings)
   15 RAG/hr × 132 hrs × 80% uncached = 1,584 queries
   Cost: 1,584 × 250 tokens × $0.00002/1K ≈ $0.01

📄 Document Embeddings
   1 doc/hr × 132 hrs = 132 documents
   132 docs × 10 pages × 500 tokens = 660,000 tokens
   Cost: 660K × $0.00002/1K = $0.01

🎖️ Cohere Rerank
   1,584 RAG queries × 1,000 tokens/query = 1.58M tokens
   Cost: 1.58M × $1.00/1M = $1.58
```

| Cost Component | Monthly Cost | % of Total |
|----------------|--------------|------------|
| 📤 GPT-4o-mini Output | $1.58 | 48% |
| 🎖️ Cohere Rerank | $1.58 | 48% |
| 📥 GPT-4o-mini Input | $0.10 | 3% |
| 📐 Embeddings | $0.02 | 1% |
| **Total per User** | **$3.28/month** | |

---

### 📈 Extrapolation to Scale

| Users | AI Cost/Month | Infrastructure | Total Monthly | Cost/User |
|-------|---------------|----------------|---------------|-----------|
| 100 | $328 | $1,309 | $1,637 | $16.37 |
| 1,000 | $3,280 | $1,309 | $4,589 | $4.59 |
| 5,000 | $16,400 | $2,618 | $19,018 | $3.80 |
| 10,000 | $32,800 | $5,236 | $38,036 | $3.80 |
| 50,000 | $164,000 | $13,090 | $177,090 | $3.54 |

---

### ⚠️ Capacity Analysis

**TPM Bottleneck (200,000 TPM OpenAI Limit):**

```
Peak Concurrent Users (all in same minute):
  200,000 TPM ÷ (1000 tokens/message * 2 messages/min/user) ≈ 100 concurrent users
```

| Bottleneck | Limit | Users Supported |
|------------|-------|-----------------|
| 🔢 OpenAI TPM | 200,000 | ~100 concurrent |
| 🖥️ EC2 Compute | 2 instances | ~100-200 concurrent |
| 🐘 RDS Connections | 100 per instance | ~200 concurrent |
| ⚡ Redis Ops/sec | 100,000 | Not a bottleneck |

**When System Breaks:** At ~1,000+ concurrent users without scaling:
- OpenAI rate limits trigger → queuing kicks in → 429s for free tier
- EC2 CPU maxes → PDF processing slows → longer wait times
- Solution: Upgrade OpenAI tier + add EC2 instances + read replicas

---

### 📊 Complete Cost Table (Infra + AI)

| Scale | Infrastructure | AI (OpenAI + Cohere) | Total | Per User |
|-------|----------------|----------------------|-------|----------|
| **100 users**  | $1,309 | $328 | **$1,637** | $16.37 |
| **1K users**  | $1,309 | $3,280 | **$4,589** | $4.59 |
| **10K users**  | $5,236 | $32,800 | **$38,036** | $3.80 |
| **100,000** | $26,180 | $328,000 | **$354,180** | $3.54 |

> *Economy of scale: Per-user cost drops from $16.37 → $3.54 as you grow!* 📉

---

## 🚧 What's Missing (The Honest Section)

*Because no project is perfect, and pretending otherwise is just bad comedy.* 🎭

**❌ Things I Didn't Get To:**

| Missing Feature | What It Would Do | Why It Matters |
|-----------------|------------------|----------------|
| 📊 **RAGAS Evals** | Evaluate RAG quality (faithfulness, relevance, context recall) | Can't improve what you can't measure |
| 🔍 **Extraction Completeness Checks** | Verify PDF parsing didn't miss sections | Tables and images sometimes vanish into the void |
| 🤖 **LLM Diversity** | Currently married to OpenAI | One API outage = entire system down. Not ideal. |
| 🗑️ **Checkpoint Cleanup/TTL** | Auto-delete old LangGraph checkpoints | Storage grows unbounded - every invoke = new checkpoint row |

**🔮 Future Additions (The Roadmap):**

```
┌─────────────────────────────────────────────────────────────────┐
│                    AFTER HITL APPROVAL                          │
│                                                                 │
│  User Approves Tweet/Post                                       │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │  SQS/Kafka  │───▶│  Consumer   │───▶│  Twitter/   │          │
│  │    Queue    │    │   Group     │    │  LinkedIn   │          │
│  └─────────────┘    └─────────────┘    │    API      │          │
│                                        └─────────────┘          │
│                                                                 │
│  Currently: Approval just returns "approved" ✅                 │
│  Future: Actually posts to your social media 🚀                 │
└─────────────────────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────────────────────┐
│                 AFTER ARXIV PAPER EMBEDDING                     │
│                                                                 │
│  Paper Embedded Successfully                                    │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │   LLM Gen   │───▶│  5-Minute   │───▶│  Public     │          │
│  │   Summary   │    │   Summary   │    │  Gallery    │          │
│  └─────────────┘    └─────────────┘    └─────────────┘          │
│                                                                 │
│  Currently: Just embeds the paper 📄                            │
│  Future: Auto-generates TL;DR for everyone to browse 📚         │
│                                                                 │
│  "Because nobody has time to read 40 pages just to find out     │
│   if the paper is relevant to them." 😅                         │
└─────────────────────────────────────────────────────────────────┘
```

**🐢 Why Is It a bit Slow?**

> *I am using consumer-grade API tiers, not enterprise ones.*

| What We Use | What Enterprises Use |
|-------------|---------------------|
| OpenAI standard tier | OpenAI with dedicated capacity |
| Qdrant Cloud free/starter | Qdrant dedicated clusters |
| Basic rate limits | Priority queues & higher limits |

*Translation: We're driving a Honda, not a Ferrari. Gets you there, just not as fast.* 🚗

---

## 🎭 Behind the Scenes

| Stat | Value |
|------|-------|
| ☕ Mass consumed | None |
| 🌙 Lines written at 2 AM | *too many to count* |
| 🔄 Times Redis will save us | *countless* |
| 💬 "It works on my machine" | *I stopped counting* |
| 🐛 Bugs fixed | *∞ - 1* |

---

<p align="center">
  <b>If you read till here, my sleepless nights were worth it.</b> 😴❤️
  <i>Built with positivity and love by <a href="https://github.com/alliedbrother">Sai Akhil </a>(I know cringe)</i>
</p>

