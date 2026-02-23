"""LinkedIn post generator subgraph."""

from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

from ..config import get_settings
from .state import LinkedInState

settings = get_settings()

MAX_ITERATIONS = 3
MIN_QUALITY_SCORE = 8.0


def build_linkedin_subgraph():
    """Build the LinkedIn post generator subgraph.

    Flow: outline → generate → critique → quality_check → (retry or done)

    Returns:
        Compiled subgraph
    """
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0.7,
    )

    def generate_outline(state: LinkedInState) -> dict:
        """Generate an outline for the LinkedIn post."""
        context_section = ""
        if state.get("context"):
            context_section = f"\n\nResearch Context:\n{state['context']}"

        prompt = f"""Create an outline for a LinkedIn post about: {state['topic']}
{context_section}

Style: {state.get('style', 'insight')}

Create a structured outline with:
1. Hook/Opening (attention-grabbing first line)
2. Main points (2-3 key insights)
3. Supporting evidence or examples
4. Call to action or thought-provoking question

Return only the outline."""

        # Configure LLM with custom run name for LangSmith tracing
        configured_llm = llm.with_config(run_name="linkedin_outline_generation")
        response = configured_llm.invoke([HumanMessage(content=prompt)])
        return {"outline": response.content}

    def generate_post(state: LinkedInState) -> dict:
        """Generate the full LinkedIn post from outline."""
        context_section = ""
        if state.get("context"):
            context_section = f"\n\nResearch Context:\n{state['context']}"

        prompt = f"""Write a LinkedIn post based on this outline:

{state['outline']}

Topic: {state['topic']}
Style: {state.get('style', 'insight')}
{context_section}

Requirements:
- Start with a compelling hook
- Use short paragraphs (1-2 sentences each)
- Include line breaks for readability
- Add relevant emojis sparingly
- End with engagement prompt (question or CTA)
- 1000-1500 characters ideal

Return only the post content."""

        # Configure LLM with custom run name for LangSmith tracing
        configured_llm = llm.with_config(run_name="linkedin_post_generation")
        response = configured_llm.invoke([HumanMessage(content=prompt)])
        return {
            "draft": response.content,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    def critique_post(state: LinkedInState) -> dict:
        """Critique the LinkedIn post."""
        prompt = f"""Critique this LinkedIn post:

"{state['draft']}"

Topic: {state['topic']}
Style: {state.get('style', 'insight')}

Evaluate on:
1. Hook strength (does first line grab attention?)
2. Value delivery (are insights actionable/interesting?)
3. Readability (formatting, paragraph length)
4. Authenticity (does it sound genuine, not AI-generated?)
5. Engagement potential (will people comment/share?)
6. Accuracy to research context (if provided)

Provide specific feedback and a quality score from 1-10.
End with: "Quality Score: X/10" """

        # Configure LLM with custom run name for LangSmith tracing
        configured_llm = llm.with_config(run_name="linkedin_critique")
        response = configured_llm.invoke([HumanMessage(content=prompt)])

        critique_text = response.content
        score = 5.0
        try:
            import re

            match = re.search(
                r"Quality Score:\s*(\d+(?:\.\d+)?)\s*/\s*10", critique_text
            )
            if match:
                score = float(match.group(1))
            else:
                match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", critique_text)
                if match:
                    score = float(match.group(1))
        except (ValueError, AttributeError):
            pass  # Keep default score on parsing errors

        return {"critique": critique_text, "quality_score": score}

    def check_quality(state: LinkedInState) -> str:
        """Decide next step based on quality and iterations."""
        if state["quality_score"] >= MIN_QUALITY_SCORE:
            return "finalize"
        elif state["iteration_count"] < MAX_ITERATIONS:
            return "regenerate"
        else:
            return "finalize"  # Accept after max iterations

    def finalize_post(state: LinkedInState) -> dict:
        """Finalize and store the post."""
        import uuid

        # TODO: Actually store to PostgreSQL
        return {
            "final_post": state["draft"],
            "post_id": str(uuid.uuid4()),
        }

    # Build graph
    builder = StateGraph(LinkedInState)

    # Add nodes
    builder.add_node("outline", generate_outline)
    builder.add_node("generate", generate_post)
    builder.add_node("critique", critique_post)
    builder.add_node("finalize", finalize_post)

    # Add edges
    builder.add_edge(START, "outline")
    builder.add_edge("outline", "generate")
    builder.add_edge("generate", "critique")
    builder.add_conditional_edges(
        "critique",
        check_quality,
        {
            "regenerate": "generate",
            "finalize": "finalize",
        },
    )
    builder.add_edge("finalize", END)

    return builder.compile()


# Build the subgraph once (lazy initialization)
_linkedin_subgraph = None

def get_linkedin_subgraph():
    """Get or create the LinkedIn subgraph."""
    global _linkedin_subgraph
    if _linkedin_subgraph is None:
        _linkedin_subgraph = build_linkedin_subgraph()
    return _linkedin_subgraph


# Tool wrapper for main agent
@tool
def linkedin_generator(
    topic: str,
    style: str = "insight",
    context: Optional[str] = None,
) -> str:
    """Generate a LinkedIn post about a topic with outline and quality loop (max 3 iterations).

    This tool:
    1. Creates an outline
    2. Generates the full post
    3. Self-critiques the post
    4. Regenerates if quality < 8/10 (max 3 iterations)
    5. Returns the finalized post

    Args:
        topic: What the post should be about
        style: Post style - "insight" (default), "announcement", "tutorial", or "story"
        context: Optional RAG context for accuracy (from rag_retriever)

    Returns:
        Generated LinkedIn post with iteration details
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
            tracker.start(thread_id, "linkedin_generator")

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

        # Step 1: Create outline
        step_msg = "Creating post outline..."
        if thread_id:
            tracker.update(thread_id, "outlining", 1, step_msg, 1)

        outline_prompt = f"""Create an outline for a LinkedIn post about: {topic}
{context_section}

Style: {style}

Create a structured outline with:
1. Hook/Opening (attention-grabbing first line)
2. Main points (2-3 key insights)
3. Supporting evidence or examples
4. Call to action or thought-provoking question

Return only the outline, be concise."""

        outline = llm.invoke([HumanMessage(content=outline_prompt)]).content
        iteration_log.append("**Outline created**")

        draft = None
        score = 0.0

        for iteration in range(1, MAX_ITER + 1):
            # Step 2: Generate post
            step_msg = f"Generating post (iteration {iteration}/{MAX_ITER})..."
            if thread_id:
                tracker.update(thread_id, "generating", 2, step_msg, iteration)

            if iteration == 1:
                # First generation from outline
                generate_prompt = f"""Write a LinkedIn post based on this outline:

{outline}

Topic: {topic}
Style: {style}
{context_section}

Requirements:
- Start with a compelling hook
- Use short paragraphs (1-2 sentences each)
- Include line breaks for readability
- Add relevant emojis sparingly (1-3 max)
- End with engagement prompt (question or CTA)
- 1000-1500 characters ideal

Return only the post content."""
            else:
                # Regeneration based on critique
                generate_prompt = f"""Improve this LinkedIn post based on the critique:

Original post:
{draft}

Critique: {critique}

Topic: {topic}
Style: {style}
{context_section}

Generate an improved post that addresses the feedback.
Return only the improved post content."""

            draft = llm.invoke([HumanMessage(content=generate_prompt)]).content

            iteration_log.append(f"**Iteration {iteration}:**")
            preview = draft[:150].replace('\n', ' ')
            iteration_log.append(f"Preview: \"{preview}...\"")

            # Step 3: Critique the post
            step_msg = f"Evaluating quality (iteration {iteration}/{MAX_ITER})..."
            if thread_id:
                tracker.update(thread_id, "evaluating", 3, step_msg, iteration, draft)

            critique_prompt = f"""Critique this LinkedIn post:

"{draft}"

Topic: {topic}
Style: {style}

Evaluate on:
1. Hook strength (does first line grab attention?)
2. Value delivery (are insights actionable/interesting?)
3. Readability (formatting, paragraph length)
4. Authenticity (does it sound genuine, not AI-generated?)
5. Engagement potential (will people comment/share?)
6. Accuracy to research context (if provided)

Be concise. End with exactly: "Score: X/10" where X is your rating."""

            critique = llm.invoke([HumanMessage(content=critique_prompt)]).content

            # Extract score
            score = 5.0  # Default
            match = re.search(r"(\d+(?:\.\d+)?)\s*[/out of]*\s*10", critique, re.IGNORECASE)
            if match:
                score = min(float(match.group(1)), 10.0)

            iteration_log.append(f"Score: {score:.1f}/10")

            if thread_id:
                tracker.update(thread_id, "evaluated", 3, f"Score: {score:.1f}/10", iteration, draft, score)

            # Check if quality is good enough
            if score >= MIN_SCORE:
                iteration_log.append("Quality threshold met!")
                break
            elif iteration < MAX_ITER:
                iteration_log.append(f"Below threshold ({MIN_SCORE}), regenerating...")

        # Complete progress tracking
        if thread_id:
            tracker.complete(thread_id, draft, score)

        # Build final response
        iterations_summary = "\n".join(iteration_log)

        return f'''{draft}

---
**Generation Details:**
{iterations_summary}

*Final Score: {score:.1f}/10 | Iterations: {iteration}/{MAX_ITER} | Style: {style}*'''

    except Exception as e:
        if thread_id:
            tracker.update(thread_id, "error", 0, f"Error: {str(e)}", 0)
        return f"Error generating LinkedIn post: {str(e)}"


linkedin_generator_tool = linkedin_generator
