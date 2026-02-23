"""Migration script to add payload indexes to existing Qdrant collection.

This script:
1. Creates payload indexes for frequently filtered fields
2. Updates existing documents to have default visibility values (optional)

Usage:
    python -m final_app.scripts.migrate_qdrant

Or run directly:
    python final_app/scripts/migrate_qdrant.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import PayloadSchemaType, Filter, FieldCondition, MatchValue, SetPayload


def get_client() -> QdrantClient:
    """Get Qdrant client from environment variables."""
    from dotenv import load_dotenv

    # Try to load .env from multiple locations
    env_paths = [
        Path(__file__).parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
        Path.cwd() / ".env",
    ]

    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"Loaded .env from: {env_path}")
            break

    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")

    if not qdrant_url:
        raise ValueError("QDRANT_URL environment variable is required")
    if not qdrant_api_key:
        raise ValueError("QDRANT_API_KEY environment variable is required")

    return QdrantClient(url=qdrant_url, api_key=qdrant_api_key)


def create_indexes(client: QdrantClient, collection_name: str) -> None:
    """Create payload indexes for frequently filtered fields.

    Args:
        client: Qdrant client
        collection_name: Name of the collection
    """
    indexes = [
        ("tenant_id", PayloadSchemaType.KEYWORD),
        ("department", PayloadSchemaType.KEYWORD),
        ("visibility", PayloadSchemaType.KEYWORD),
        ("uploaded_by_user_id", PayloadSchemaType.KEYWORD),
        ("arxiv_id", PayloadSchemaType.KEYWORD),
        ("document_name", PayloadSchemaType.KEYWORD),
    ]

    print(f"\nCreating indexes for collection: {collection_name}")
    print("-" * 50)

    for field_name, field_type in indexes:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=field_type,
            )
            print(f"  [OK] Created index: {field_name}")
        except Exception as e:
            error_msg = str(e).lower()
            if "already exists" in error_msg or "duplicate" in error_msg:
                print(f"  [SKIP] Index already exists: {field_name}")
            else:
                print(f"  [ERROR] Failed to create index {field_name}: {e}")


def backfill_visibility(
    client: QdrantClient,
    collection_name: str,
    default_visibility: str = "public",
    default_user_id: str = "anonymous"
) -> None:
    """Backfill visibility and uploaded_by_user_id for existing documents.

    This is optional - documents without these fields are handled by the
    visibility filter as legacy documents.

    Args:
        client: Qdrant client
        collection_name: Name of the collection
        default_visibility: Default visibility value
        default_user_id: Default user ID
    """
    print(f"\nBackfilling visibility for collection: {collection_name}")
    print("-" * 50)

    # Scroll through all points and update those missing visibility
    offset = None
    updated_count = 0
    batch_size = 100

    while True:
        results, offset = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not results:
            break

        for point in results:
            payload = point.payload or {}

            # Check if visibility is missing
            if "visibility" not in payload:
                try:
                    client.set_payload(
                        collection_name=collection_name,
                        payload={
                            "visibility": default_visibility,
                            "uploaded_by_user_id": payload.get("uploaded_by_user_id", default_user_id),
                        },
                        points=[point.id],
                    )
                    updated_count += 1
                except Exception as e:
                    print(f"  [ERROR] Failed to update point {point.id}: {e}")

        if offset is None:
            break

        print(f"  Processed batch, updated {updated_count} points so far...")

    print(f"\n  [DONE] Updated {updated_count} points with default visibility")


def get_collection_info(client: QdrantClient, collection_name: str) -> dict:
    """Get collection information.

    Args:
        client: Qdrant client
        collection_name: Name of the collection

    Returns:
        Collection info dict
    """
    try:
        info = client.get_collection(collection_name)
        return {
            "exists": True,
            "points_count": info.points_count,
            "vectors_count": info.vectors_count,
            "status": info.status.value if info.status else "unknown",
            "payload_schema": {
                k: v.data_type.value if hasattr(v, "data_type") else str(v)
                for k, v in (info.payload_schema or {}).items()
            },
        }
    except Exception as e:
        if "not found" in str(e).lower():
            return {"exists": False}
        raise


def migrate(
    collection_name: str = "research_papers",
    backfill: bool = False,
) -> None:
    """Run the migration.

    Args:
        collection_name: Name of the Qdrant collection
        backfill: Whether to backfill visibility for existing documents
    """
    print("=" * 60)
    print("QDRANT MIGRATION SCRIPT")
    print("=" * 60)

    client = get_client()

    # Check collection exists
    info = get_collection_info(client, collection_name)
    if not info.get("exists"):
        print(f"\n[ERROR] Collection '{collection_name}' does not exist!")
        print("Create the collection first by uploading a document.")
        return

    print(f"\nCollection: {collection_name}")
    print(f"Points count: {info.get('points_count', 0)}")
    print(f"Status: {info.get('status', 'unknown')}")

    # Show existing payload schema
    if info.get("payload_schema"):
        print("\nExisting payload indexes:")
        for field, dtype in info["payload_schema"].items():
            print(f"  - {field}: {dtype}")

    # Create indexes
    create_indexes(client, collection_name)

    # Optionally backfill visibility
    if backfill:
        backfill_visibility(client, collection_name)

    # Show final state
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)

    final_info = get_collection_info(client, collection_name)
    if final_info.get("payload_schema"):
        print("\nFinal payload indexes:")
        for field, dtype in final_info["payload_schema"].items():
            print(f"  - {field}: {dtype}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate Qdrant collection")
    parser.add_argument(
        "--collection",
        default="research_papers",
        help="Collection name (default: research_papers)",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Backfill visibility for existing documents",
    )

    args = parser.parse_args()
    migrate(collection_name=args.collection, backfill=args.backfill)
