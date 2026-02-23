"""Migration script to move conversations from messages table to PostgresSaver checkpoints.

This script reads existing conversations from the messages table and creates
LangGraph checkpoints in PostgreSQL so conversation history persists.

Run this once before switching to PostgresSaver:
    python -m final_app.scripts.migrate_to_postgres_checkpointer
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.postgres import PostgresSaver

from final_app.config import get_settings

settings = get_settings()


def get_existing_conversations():
    """Get all conversations from the messages table."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
    )

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get all messages grouped by thread_id, ordered by created_at
            cur.execute("""
                SELECT thread_id, role, content, created_at
                FROM messages
                ORDER BY thread_id, created_at ASC
            """)
            rows = cur.fetchall()

            # Group by thread_id
            conversations = {}
            for row in rows:
                thread_id = row['thread_id']
                if thread_id not in conversations:
                    conversations[thread_id] = []
                conversations[thread_id].append({
                    'role': row['role'],
                    'content': row['content'],
                    'created_at': row['created_at'],
                })

            return conversations
    finally:
        conn.close()


def migrate_to_postgres_saver():
    """Migrate all conversations to PostgresSaver checkpoints."""
    print("Starting migration to PostgresSaver...")

    # Get existing conversations
    conversations = get_existing_conversations()
    print(f"Found {len(conversations)} conversations to migrate")

    if not conversations:
        print("No conversations to migrate.")
        return

    # Initialize PostgresSaver using context manager
    with PostgresSaver.from_conn_string(settings.postgres_url) as checkpointer:
        checkpointer.setup()
        print("PostgresSaver initialized and tables created")

        # Build the agent graph (needed to create valid checkpoints)
        from final_app.graphs.main_graph import build_main_agent
        agent = build_main_agent(checkpointer=checkpointer)

        migrated = 0
        failed = 0

        for thread_id, messages in conversations.items():
            try:
                # Convert messages to LangChain format
                langchain_messages = []
                for msg in messages:
                    if msg['role'] == 'user':
                        langchain_messages.append(HumanMessage(content=msg['content'] or ""))
                    elif msg['role'] == 'assistant':
                        langchain_messages.append(AIMessage(content=msg['content'] or ""))

                if not langchain_messages:
                    continue

                # Create config for this thread
                config = {"configurable": {"thread_id": thread_id}}

                # Use update_state to add messages to the checkpoint
                # This creates a valid checkpoint with the conversation history
                agent.update_state(
                    config,
                    {"messages": langchain_messages},
                )

                migrated += 1
                print(f"  Migrated thread {thread_id[:8]}... ({len(langchain_messages)} messages)")

            except Exception as e:
                failed += 1
                print(f"  Failed to migrate thread {thread_id[:8]}...: {e}")

        print(f"\nMigration complete!")
        print(f"  Migrated: {migrated}")
        print(f"  Failed: {failed}")


def verify_migration():
    """Verify that conversations were migrated correctly."""
    print("\nVerifying migration...")

    conversations = get_existing_conversations()

    # Initialize PostgresSaver and agent using context manager
    with PostgresSaver.from_conn_string(settings.postgres_url) as checkpointer:
        from final_app.graphs.main_graph import build_main_agent
        agent = build_main_agent(checkpointer=checkpointer)

        verified = 0
        for thread_id in list(conversations.keys())[:5]:  # Check first 5
            config = {"configurable": {"thread_id": thread_id}}
            try:
                state = agent.get_state(config)
                if state.values and state.values.get("messages"):
                    msg_count = len(state.values["messages"])
                    print(f"  Thread {thread_id[:8]}...: {msg_count} messages in checkpoint")
                    verified += 1
            except Exception as e:
                print(f"  Thread {thread_id[:8]}...: Error - {e}")

        print(f"\nVerified {verified} conversations have checkpoints")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate conversations to PostgresSaver")
    parser.add_argument("--verify-only", action="store_true", help="Only verify, don't migrate")
    args = parser.parse_args()

    if args.verify_only:
        verify_migration()
    else:
        migrate_to_postgres_saver()
        verify_migration()
