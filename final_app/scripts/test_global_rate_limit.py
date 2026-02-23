"""Test script for global rate limiting.

This script sends multiple concurrent requests to test the global rate limit.
Uses multiple super users to avoid per-user rate limits.

Global limit: 8 req/min (test setting)
Per-user limit: 5 req/min for super users

Strategy: Use 2 super users, send 5 requests each = 10 total
Expected: First 8 succeed immediately, last 2 get queued
"""

import asyncio
import aiohttp
import json
import time
from typing import Optional

# Configuration
API_URL = "http://localhost:8000/api/v1/chat/stream"

# Get super user IDs from database (run this query to find them):
# SELECT id, email, tier FROM users WHERE tier = 'super' LIMIT 2;
# For now, we'll use placeholder UUIDs - replace with actual user IDs
SUPER_USERS = [
    # Replace these with actual super user IDs from your database
    None,  # Will use anonymous (no per-user limit check)
    None,
]


async def send_request(
    session: aiohttp.ClientSession,
    request_num: int,
    user_id: Optional[str] = None,
) -> dict:
    """Send a chat request and capture the response."""
    start_time = time.time()

    payload = {
        "message": f"Test request #{request_num} - What is 2+2?",
        "thread_id": f"test-global-limit-{request_num}",
        "user_id": user_id,
        "tenant_id": "test-tenant",
        "department": "test-dept",
    }

    result = {
        "request_num": request_num,
        "user_id": user_id or "anonymous",
        "events": [],
        "status": "unknown",
        "queued": False,
        "queue_position": None,
        "error": None,
    }

    try:
        async with session.post(API_URL, json=payload) as response:
            result["http_status"] = response.status
            result["headers"] = {
                "X-RateLimit-Limit": response.headers.get("X-RateLimit-Limit"),
                "X-RateLimit-Remaining": response.headers.get("X-RateLimit-Remaining"),
                "X-Global-RateLimit-Limit": response.headers.get("X-Global-RateLimit-Limit"),
                "X-Global-RateLimit-Remaining": response.headers.get("X-Global-RateLimit-Remaining"),
                "X-Queue-Position": response.headers.get("X-Queue-Position"),
            }

            # Read SSE events
            async for line in response.content:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    try:
                        event = json.loads(line[6:])
                        result["events"].append(event)

                        if event.get("type") == "queue":
                            result["queued"] = True
                            result["queue_position"] = event.get("position")
                            print(f"  Request #{request_num}: QUEUED at position {event.get('position')} - {event.get('message')}")

                        elif event.get("type") == "error":
                            result["status"] = "error"
                            result["error"] = event.get("message")
                            if event.get("rate_limit"):
                                print(f"  Request #{request_num}: RATE LIMITED - {event.get('message')}")
                            elif event.get("queue_full"):
                                print(f"  Request #{request_num}: QUEUE FULL - {event.get('message')}")
                            else:
                                print(f"  Request #{request_num}: ERROR - {event.get('message')}")

                        elif event.get("type") == "result":
                            result["status"] = "success"
                            # Don't print full response, just confirm success

                    except json.JSONDecodeError:
                        pass

    except Exception as e:
        result["status"] = "exception"
        result["error"] = str(e)
        print(f"  Request #{request_num}: EXCEPTION - {e}")

    result["duration_ms"] = int((time.time() - start_time) * 1000)
    return result


async def run_sequential_test(num_requests: int = 10):
    """Send requests one at a time to see rate limiting in action."""
    print(f"\n{'='*60}")
    print("SEQUENTIAL TEST - Sending {num_requests} requests one at a time")
    print(f"{'='*60}\n")

    results = []

    async with aiohttp.ClientSession() as session:
        for i in range(1, num_requests + 1):
            print(f"Sending request #{i}...")
            result = await send_request(session, i)
            results.append(result)

            if result["status"] == "success":
                print(f"  Request #{i}: SUCCESS in {result['duration_ms']}ms")

            # Small delay to see the progression
            await asyncio.sleep(0.1)

    return results


async def run_concurrent_test(num_requests: int = 10):
    """Send multiple requests concurrently to stress test global limit."""
    print(f"\n{'='*60}")
    print(f"CONCURRENT TEST - Sending {num_requests} requests simultaneously")
    print(f"{'='*60}\n")

    async with aiohttp.ClientSession() as session:
        tasks = [
            send_request(session, i)
            for i in range(1, num_requests + 1)
        ]

        print("Firing all requests...")
        results = await asyncio.gather(*tasks)

    return results


def print_summary(results: list):
    """Print test summary."""
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}\n")

    success = sum(1 for r in results if r["status"] == "success")
    queued = sum(1 for r in results if r["queued"])
    rate_limited = sum(1 for r in results if r.get("error") and "rate limit" in r.get("error", "").lower())
    queue_full = sum(1 for r in results if any(e.get("queue_full") for e in r.get("events", [])))
    errors = sum(1 for r in results if r["status"] == "error" and not r.get("queued"))

    print(f"Total requests:    {len(results)}")
    print(f"Successful:        {success}")
    print(f"Queued:            {queued}")
    print(f"Rate limited:      {rate_limited}")
    print(f"Queue full:        {queue_full}")
    print(f"Other errors:      {errors}")

    # Show timing
    durations = [r["duration_ms"] for r in results if r.get("duration_ms")]
    if durations:
        print(f"\nResponse times:")
        print(f"  Min: {min(durations)}ms")
        print(f"  Max: {max(durations)}ms")
        print(f"  Avg: {sum(durations)//len(durations)}ms")

    # Show global rate limit headers from first response
    if results and results[0].get("headers"):
        headers = results[0]["headers"]
        print(f"\nRate limit headers (from first response):")
        for key, value in headers.items():
            if value:
                print(f"  {key}: {value}")


async def check_current_status():
    """Check current rate limit status before testing."""
    print(f"\n{'='*60}")
    print("CHECKING CURRENT RATE LIMIT STATUS")
    print(f"{'='*60}\n")

    async with aiohttp.ClientSession() as session:
        # Check health
        async with session.get("http://localhost:8000/api/v1/chat/usage/health") as resp:
            health = await resp.json()
            print(f"Health: {health.get('status')}")
            print(f"  User rate limiter: {health.get('user_rate_limiter')}")
            print(f"  Global rate limiter: {health.get('global_rate_limiter')}")

        # Check queue
        async with session.get("http://localhost:8000/api/v1/chat/usage/queue") as resp:
            queue = await resp.json()
            print(f"\nGlobal status:")
            print(f"  Current count: {queue.get('current_count')}/{queue.get('limit')}")
            print(f"  Queue size: {queue.get('queue_size')}/{queue.get('max_queue_size')}")
            print(f"  Processing: {queue.get('processing_count')}")


async def main():
    """Run the test suite."""
    print("\n" + "="*60)
    print("GLOBAL RATE LIMIT TEST")
    print("="*60)
    print(f"\nSettings:")
    print(f"  Global limit: 8 requests/minute (test setting)")
    print(f"  Per-user limit: 5 req/min (super), 3 req/min (free/power)")
    print(f"  Queue max size: 100")
    print(f"  Queue max wait: 60 seconds")

    # Check current status
    await check_current_status()

    # Wait for user input
    print("\n" + "-"*60)
    input("Press Enter to start the test (sends 10 requests)...")

    # Run sequential test
    results = await run_sequential_test(num_requests=10)
    print_summary(results)

    print("\n" + "-"*60)
    print("Test complete!")
    print("\nTo run concurrent test, modify the script and call run_concurrent_test()")


if __name__ == "__main__":
    asyncio.run(main())
