"""Twitter tweet generator subgraph."""

from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from ..config import get_settings
from .state import TwitterState

settings = get_settings()

MAX_ITERATIONS = 3
MIN_QUALITY_SCORE = 8.0


def build_twitter_subgraph():
    """Build the Twitter generator subgraph.

    Flow: generate → critique → quality_check → (retry or HITL) → store

    Returns:
        Compiled subgraph
    """
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0.7,
    )

    def generate_tweet(state: TwitterState) -> dict:
        """Generate a tweet draft."""
        context_section = ""
        if state.get("context"):
            context_section = f"\n\nResearch Context:\n{state['context']}"

        prompt = f"""Generate a compelling tweet about: {state['topic']}
{context_section}

Requirements:
- Maximum 280 characters
- Engaging and informative
- Include relevant hashtags
- Be accurate to the research context if provided

Return ONLY the tweet text, nothing else."""

        # Configure LLM with custom run name for LangSmith tracing
        configured_llm = llm.with_config(run_name="twitter_draft_generation")
        response = configured_llm.invoke([HumanMessage(content=prompt)])
        return {
            "draft": response.content,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    def critique_tweet(state: TwitterState) -> dict:
        """Critique the tweet draft."""
        prompt = f"""Critique this tweet:

"{state['draft']}"

Topic: {state['topic']}

Evaluate on:
1. Accuracy (if research context provided)
2. Engagement potential
3. Clarity and conciseness
4. Appropriate use of hashtags
5. Character count (must be ≤280)

Provide specific, actionable feedback for improvement.
End with a quality score from 1-10."""

        # Configure LLM with custom run name for LangSmith tracing
        configured_llm = llm.with_config(run_name="twitter_critique")
        response = configured_llm.invoke([HumanMessage(content=prompt)])

        # Extract score from response (simple parsing)
        critique_text = response.content
        score = 5.0  # Default
        try:
            # Look for patterns like "8/10" or "Score: 8"
            import re

            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:/\s*10|out of 10)?", critique_text)
            if match:
                score = float(match.group(1))
        except (ValueError, AttributeError):
            pass  # Keep default score on parsing errors

        return {"critique": critique_text, "quality_score": score}

    def check_quality(state: TwitterState) -> str:
        """Decide next step based on quality score and iterations."""
        if state["quality_score"] >= MIN_QUALITY_SCORE:
            return "request_approval"
        elif state["iteration_count"] < MAX_ITERATIONS:
            return "regenerate"
        else:
            return "request_approval"  # Force approval after max iterations

    def request_approval(state: TwitterState) -> dict:
        """Request human approval (HITL)."""
        # Interrupt execution for human approval
        approval = interrupt({
            "type": "tweet_approval",
            "draft": state["draft"],
            "quality_score": state["quality_score"],
            "iterations": state["iteration_count"],
            "topic": state["topic"],
        })

        return {"approved": approval.get("approved", False)}

    def store_tweet(state: TwitterState) -> dict:
        """Store approved tweet to database."""
        if state.get("approved"):
            # TODO: Actually store to PostgreSQL
            import uuid

            return {
                "final_tweet": state["draft"],
                "tweet_id": str(uuid.uuid4()),
            }
        return {"final_tweet": None, "tweet_id": None}

    def should_store(state: TwitterState) -> str:
        """Check if tweet should be stored."""
        if state.get("approved"):
            return "store"
        return END

    # Build graph
    builder = StateGraph(TwitterState)

    # Add nodes
    builder.add_node("generate", generate_tweet)
    builder.add_node("critique", critique_tweet)
    builder.add_node("request_approval", request_approval)
    builder.add_node("store", store_tweet)

    # Add edges
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "critique")
    builder.add_conditional_edges(
        "critique",
        check_quality,
        {
            "regenerate": "generate",
            "request_approval": "request_approval",
        },
    )
    builder.add_conditional_edges(
        "request_approval",
        should_store,
        {"store": "store", END: END},
    )
    builder.add_edge("store", END)

    return builder.compile()


# Tool wrapper for main agent
@tool
def twitter_generator(
    topic: str,
    context: Optional[str] = None,
) -> str:
    """Generate a tweet about a topic with critique loop (max 3 iterations).

    This tool generates a tweet by:
    1. Generating a tweet draft
    2. Self-critiques the draft
    3. Regenerates if quality < 8/10 (max 3 iterations)
    4. Returns the best version after max iterations or when quality >= 8

    Args:
        topic: What the tweet should be about
        context: Optional RAG context for accuracy (from rag_retriever)

    Returns:
        Generated tweet with iteration details
    """
    import re
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
    from ..services.progress_tracker import get_progress_tracker, get_current_thread_id

    settings = get_settings()
    tracker = get_progress_tracker()
    thread_id = get_current_thread_id()

    MAX_ITER = 3
    MIN_SCORE = 8.0

    try:
        # Start progress tracking
        if thread_id:
            tracker.start(thread_id, "twitter_generator")

        llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.7,
        )

        # Build context section if provided
        context_section = ""
        if context:
            context_section = f"\n\nResearch Context (use this for accuracy):\n{context}"

        iteration_log = []
        draft = None
        score = 0.0

        for iteration in range(1, MAX_ITER + 1):
            # Step 1: Generate tweet
            step_msg = f"Generating tweet (iteration {iteration}/{MAX_ITER})..."
            if thread_id:
                tracker.update(thread_id, "generating", 1, step_msg, iteration)

            if iteration == 1:
                # First generation
                generate_prompt = f"""Generate a compelling tweet about: {topic}
{context_section}

Requirements:
- Maximum 280 characters
- Engaging and informative
- Include relevant hashtags (1-3)
- Be accurate to the research context if provided
- Make it shareable and thought-provoking

Return ONLY the tweet text, nothing else."""
            else:
                # Regeneration based on critique
                generate_prompt = f"""Improve this tweet based on the critique:

Original tweet: "{draft}"

Critique: {critique}

Topic: {topic}
{context_section}

Generate an improved tweet (max 280 chars) that addresses the feedback.
Return ONLY the improved tweet text."""

            draft = llm.invoke([HumanMessage(content=generate_prompt)]).content.strip()

            # Clean up draft (remove quotes if present)
            if draft.startswith('"') and draft.endswith('"'):
                draft = draft[1:-1]

            iteration_log.append(f"**Iteration {iteration}:**")
            iteration_log.append(f"Draft: \"{draft[:100]}{'...' if len(draft) > 100 else ''}\"")

            # Step 2: Critique the tweet
            step_msg = f"Evaluating quality (iteration {iteration}/{MAX_ITER})..."
            if thread_id:
                tracker.update(thread_id, "evaluating", 2, step_msg, iteration, draft)

            critique_prompt = f"""Critique this tweet:

"{draft}"

Topic: {topic}

Evaluate on:
1. Accuracy (if research context was provided)
2. Engagement potential
3. Clarity and conciseness
4. Appropriate use of hashtags
5. Character count (must be ≤280)

Be concise. End with exactly: "Score: X/10" where X is your rating."""

            critique = llm.invoke([HumanMessage(content=critique_prompt)]).content

            # Extract score
            score = 5.0  # Default
            match = re.search(r"(\d+(?:\.\d+)?)\s*[/out of]*\s*10", critique, re.IGNORECASE)
            if match:
                score = min(float(match.group(1)), 10.0)

            iteration_log.append(f"Score: {score:.1f}/10")

            if thread_id:
                tracker.update(thread_id, "evaluated", 2, f"Score: {score:.1f}/10", iteration, draft, score)

            # Check if quality is good enough
            if score >= MIN_SCORE:
                iteration_log.append(f"Quality threshold met!")
                break
            elif iteration < MAX_ITER:
                iteration_log.append(f"Below threshold ({MIN_SCORE}), regenerating...")

        # Complete progress tracking
        if thread_id:
            tracker.complete(thread_id, draft, score)

        # Build final response
        iterations_summary = "\n".join(iteration_log)

        return f'''"{draft}"

---
**Generation Details:**
{iterations_summary}

*Final Score: {score:.1f}/10 | Iterations: {iteration}/{MAX_ITER}*'''

    except Exception as e:
        if thread_id:
            tracker.update(thread_id, "error", 0, f"Error: {str(e)}", 0)
        return f"Error generating tweet: {str(e)}"


twitter_generator_tool = twitter_generator
