#!/bin/bash
# Test global rate limit (8 req/min for testing)
# Sends 10 requests rapidly to trigger queuing

API_URL="http://localhost:8000/api/v1/chat/stream"

echo "=========================================="
echo "GLOBAL RATE LIMIT TEST"
echo "=========================================="
echo ""
echo "Global limit: 8 req/min"
echo "Sending 10 requests rapidly..."
echo ""

# Check current status first
echo "Current queue status:"
curl -s http://localhost:8000/api/v1/chat/usage/queue | python3 -m json.tool
echo ""
echo "------------------------------------------"
echo ""

# Send 10 requests in background and capture output
for i in {1..10}; do
    echo "Request #$i:"
    curl -s -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"message\": \"Test request $i - What is $i + $i?\",
            \"thread_id\": \"test-global-$i-$(date +%s)\",
            \"tenant_id\": \"test\",
            \"department\": \"test\"
        }" | while read -r line; do
            if [[ "$line" == data:* ]]; then
                event=$(echo "$line" | sed 's/^data: //')
                type=$(echo "$event" | python3 -c "import sys,json; print(json.load(sys.stdin).get('type',''))" 2>/dev/null)

                case "$type" in
                    "queue")
                        position=$(echo "$event" | python3 -c "import sys,json; print(json.load(sys.stdin).get('position','?'))" 2>/dev/null)
                        echo "  -> QUEUED at position $position"
                        ;;
                    "error")
                        msg=$(echo "$event" | python3 -c "import sys,json; print(json.load(sys.stdin).get('message',''))" 2>/dev/null)
                        echo "  -> ERROR: $msg"
                        ;;
                    "status")
                        msg=$(echo "$event" | python3 -c "import sys,json; print(json.load(sys.stdin).get('message',''))" 2>/dev/null)
                        echo "  -> STATUS: $msg"
                        ;;
                    "result")
                        echo "  -> SUCCESS (response received)"
                        break
                        ;;
                esac
            fi
        done
    echo ""
done

echo "------------------------------------------"
echo "Final queue status:"
curl -s http://localhost:8000/api/v1/chat/usage/queue | python3 -m json.tool
