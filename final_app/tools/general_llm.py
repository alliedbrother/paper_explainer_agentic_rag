"""General LLM tool for arbitrary tasks."""

import logging
from typing import Optional

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@tool
def general_llm(
    task: str,
    context: Optional[str] = None,
) -> str:
    """Call an LLM for general knowledge tasks ONLY.

    IMPORTANT: DO NOT use this tool for:
    - LinkedIn posts (use linkedin_generator instead)
    - Tweets or Twitter content (use twitter_generator instead)
    - Any social media content generation

    Use this ONLY for:
    - Explaining concepts or answering general knowledge questions
    - Summarizing text or documents
    - Translation between languages
    - Code explanation or technical clarification

    Args:
        task: Description of what you need the LLM to do
        context: Optional additional context to include

    Returns:
        LLM response
    """
    try:
        # Use LangChain wrapper for proper tracing
        llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.7,
            max_tokens=1000,
            timeout=settings.openai_timeout,
            max_retries=settings.openai_max_retries,
        ).with_config(run_name="general_llm_call")

        # Build messages
        messages = [
            SystemMessage(content=(
                "You are a helpful assistant. Provide clear, accurate, "
                "and concise responses to the user's request."
            ))
        ]

        user_content = f"Task: {task}"
        if context:
            user_content += f"\n\nContext:\n{context}"

        messages.append(HumanMessage(content=user_content))

        # Call LLM with tracing
        response = llm.invoke(messages)
        return response.content

    except Exception as e:
        error_msg = str(e)
        logger.error(f"General LLM error: {error_msg}")
        if "api_key" in error_msg.lower():
            return (
                "OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file."
            )
        return f"LLM error: {error_msg}"
