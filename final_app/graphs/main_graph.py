"""Main ReAct agent graph."""

from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.postgres import PostgresSaver

from ..config import get_settings
from ..tools import calculator, expense_manager, rag_retriever, general_llm
from .state import AgentState
from .twitter_graph import build_twitter_subgraph, twitter_generator_tool
from .linkedin_graph import build_linkedin_subgraph, linkedin_generator_tool
from .embedder_graph import build_embedder_subgraph, document_embedder_tool

settings = get_settings()

SYSTEM_PROMPT_TEMPLATE = """You are a helpful research assistant with access to specialized tools.

## Available Tools:
1. **calculator** - Evaluate mathematical expressions
2. **expense_manager** - Track user expenses (add, list, summary, delete)
3. **rag_retriever** - Search embedded research papers for context
4. **general_llm** - Handle general knowledge questions, explanations, summaries (NOT for social media)
5. **twitter_generator** - Generate tweets with self-critique loop
6. **linkedin_generator** - Generate LinkedIn posts with outline and quality check
7. **document_embedder** - Embed documents/papers into the RAG system

## MANDATORY TOOL SELECTION RULES:

**SOCIAL MEDIA CONTENT - ALWAYS USE SPECIALIZED TOOLS:**
- For ANY request involving "LinkedIn", "LinkedIn post", "post on LinkedIn" → MUST use `linkedin_generator`
- For ANY request involving "tweet", "Twitter", "X post" → MUST use `twitter_generator`
- NEVER use `general_llm` for LinkedIn or Twitter content generation

**WHEN TO USE EACH TOOL:**
- `linkedin_generator`: User mentions LinkedIn, professional post, LinkedIn article
- `twitter_generator`: User mentions tweet, Twitter, X (social media)
- `calculator`: Mathematical expressions, calculations
- `expense_manager`: Adding, listing, or managing expenses
- `rag_retriever`: Searching knowledge base (usually pre-fetched, see below)
- `general_llm`: ONLY for general questions, explanations, summaries - NOT social media
- `document_embedder`: Embedding new documents into the system

## CRITICAL RULES:

1. **Pre-fetched RAG Context**: If RAG context is provided below, USE IT when calling
   `twitter_generator` or `linkedin_generator` by passing it as the `context` parameter.
   This ensures content is accurate and based on the user's knowledge base.

2. **Tool chaining**: You can chain multiple tools. For example:
   - User asks for LinkedIn post → call `linkedin_generator(topic=..., context=<RAG context if available>)`
   - User asks for tweet → call `twitter_generator(topic=..., context=<RAG context if available>)`

3. **Be accurate**: Only include information from RAG context or verified sources.

4. **Expense tracking**: User identity is AUTOMATIC - never ask for user_id.
   Just call expense_manager with action, amount, category, etc. The system knows who the user is.

5. **Document embedding**: Users can embed arXiv papers by providing the arXiv ID or URL.
   Just call document_embedder with the arxiv_id. The system automatically uses the user's
   tenant and department. Example: "Embed paper 1706.03762" → document_embedder(arxiv_id="1706.03762")

6. **User Context**: All tools automatically know the current user. NEVER ask for user_id, tenant_id,
   or other identity information - these are handled by the system.

7. **IMPORTANT - Multi-turn conversations**: When a tool call fails due to missing parameters and you
   ask the user for more information, REMEMBER THE ORIGINAL ACTION. When the user provides the missing
   info, COMPLETE THE ORIGINAL ACTION - don't switch to a different action.

   Example:
   - User: "Add expense $60" → You call add but category is missing → Ask for category
   - User: "food" → COMPLETE THE ADD with action="add", amount=60, category="food"
   - DO NOT switch to "list" or "summary" - complete the pending "add" action!

{rag_context_section}
"""


def get_system_prompt(rag_context: str = None) -> str:
    """Build system prompt with optional RAG context."""
    if rag_context:
        rag_context_section = f"""## Pre-fetched RAG Context (USE THIS for content generation tools):
{rag_context}
"""
    else:
        rag_context_section = ""

    return SYSTEM_PROMPT_TEMPLATE.format(rag_context_section=rag_context_section)


def build_main_agent(checkpointer=None):
    """Build the main ReAct agent graph.

    Args:
        checkpointer: Optional checkpointer for state persistence.
                     If None, uses in-memory state.

    Returns:
        Compiled LangGraph agent
    """
    # Initialize LLM
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    # Collect all tools
    all_tools = [
        calculator,
        expense_manager,
        rag_retriever,
        general_llm,
        twitter_generator_tool,
        linkedin_generator_tool,
        document_embedder_tool,
    ]

    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(all_tools)

    def agent_node(state: AgentState) -> dict:
        """Main agent reasoning node."""
        # Build system prompt with RAG context if available
        rag_context = state.get("rag_context")
        system_prompt = get_system_prompt(rag_context)

        # Configure LLM with custom run name for LangSmith tracing
        configured_llm = llm_with_tools.with_config(
            run_name="react_agent_reasoning",
            metadata={"node": "agent", "has_rag_context": rag_context is not None}
        )

        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = configured_llm.invoke(messages)
        return {"messages": [response]}

    # Build graph
    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(all_tools))

    # Add edges
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "agent")  # Loop back for ReAct pattern

    # Compile with checkpointer
    return builder.compile(checkpointer=checkpointer)


def get_postgres_checkpointer():
    """Get PostgreSQL checkpointer for production use.

    Returns:
        PostgresSaver instance
    """
    return PostgresSaver.from_conn_string(settings.postgres_url)
