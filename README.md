# Paper Explainer - Agentic RAG System

A production-grade Agentic RAG (Retrieval-Augmented Generation) system for research paper analysis and Q&A, built with FastAPI, LangGraph, and React.

**Live at:** https://mlinterviewnotes.com

## Features

- **Intelligent Paper Analysis**: Upload PDFs and ask questions about research papers
- **Agentic RAG**: Uses LangGraph for multi-step reasoning with tool use
- **Semantic Search**: Vector search with Qdrant and reranking with Cohere
- **Response Caching**: Semantic similarity-based caching for faster responses
- **Rate Limiting**: Per-user and global rate limiting with Redis
- **Multi-tenant**: Support for multiple users with PostgreSQL
- **Real-time Streaming**: SSE-based streaming responses
- **Social Content Generation**: Generate LinkedIn posts and Twitter threads from papers

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   React     │────▶│   FastAPI   │────▶│  LangGraph  │
│  Frontend   │◀────│   Backend   │◀────│   Agent     │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                    │
                    ┌──────┴──────┐      ┌──────┴──────┐
                    │             │      │             │
               ┌────▼────┐  ┌────▼────┐  │   Tools     │
               │PostgreSQL│  │  Redis  │  │ - RAG      │
               │         │  │         │  │ - Calculator│
               └─────────┘  └─────────┘  │ - LLM      │
                                         └──────┬──────┘
                                                │
                                         ┌──────▼──────┐
                                         │   Qdrant    │
                                         │   Vector DB │
                                         └─────────────┘
```

## Tech Stack

- **Backend**: FastAPI, LangGraph, SQLAlchemy, asyncpg
- **Frontend**: React, Vite, TailwindCSS, shadcn/ui
- **Database**: PostgreSQL (users, sessions, checkpoints)
- **Vector Store**: Qdrant Cloud
- **Cache/Rate Limiting**: Redis
- **LLM**: OpenAI GPT-4o-mini
- **Embeddings**: OpenAI text-embedding-3-small
- **Reranking**: Cohere rerank-v3.5

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16+
- Redis 7+
- Docker (optional)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/alliedbrother/paper_explainer_agentic_rag.git
cd paper_explainer_agentic_rag
```

2. Create and activate virtual environment:
```bash
cd final_app
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys and database credentials
```

4. Start PostgreSQL and Redis (with Docker):
```bash
docker run -d --name postgres -p 5432:5432 -e POSTGRES_PASSWORD=password postgres:16
docker run -d --name redis -p 6379:6379 redis:7
```

5. Run the backend:
```bash
python run.py
# or
uvicorn final_app.main:app --reload
```

6. In a new terminal, build and serve the frontend:
```bash
cd final_app/frontend
npm install
npm run dev
```

7. Open http://localhost:5173

## Deployment

See [deploy/README.md](final_app/deploy/README.md) for AWS deployment instructions.

### Quick Deploy to AWS

```bash
# On EC2 instance
curl -O https://raw.githubusercontent.com/alliedbrother/paper_explainer_agentic_rag/main/final_app/deploy/scripts/initial-deploy.sh
chmod +x initial-deploy.sh
sudo ./initial-deploy.sh https://github.com/alliedbrother/paper_explainer_agentic_rag.git
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/v1/auth/register` | POST | User registration |
| `/api/v1/auth/login` | POST | User login |
| `/api/v1/chat/stream` | POST | Stream chat response (SSE) |
| `/api/v1/chat/sessions` | GET | List chat sessions |
| `/api/v1/embed/upload` | POST | Upload PDF for embedding |
| `/api/v1/embed/process` | POST | Process uploaded PDF |

## Environment Variables

See [.env.example](.env.example) for all configuration options.

Required:
- `OPENAI_API_KEY` - OpenAI API key
- `POSTGRES_USER` - PostgreSQL username
- `POSTGRES_PASSWORD` - PostgreSQL password
- `QDRANT_URL` - Qdrant Cloud URL
- `QDRANT_API_KEY` - Qdrant API key

## License

MIT
