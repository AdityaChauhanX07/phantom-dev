#!/bin/bash
# Setup .env files for all components

set -e

echo "🔧 Setting up .env files..."

# 1. Executor .env
echo "📝 Creating executor/.env..."
cat > executor/.env << 'EOF'
# Executor Configuration
# WebSocket URL for connecting to the agent backend
AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/executor

# Gemini API Key for vision and task planning
# Get from: https://aistudio.google.com/apikey
# IMPORTANT: Replace YOUR_GEMINI_API_KEY_HERE with your actual API key!
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE

# Execution mode: 'local' or 'cloud'
# local: Run tasks directly without WebSocket
# cloud: Connect to agent and wait for tasks
PHANTOM_MODE=cloud
EOF
echo "✅ Created executor/.env"

# 2. Dashboard .env.local
echo "📝 Creating dashboard/.env.local..."
cat > dashboard/.env.local << 'EOF'
NEXT_PUBLIC_AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/dashboard
EOF
echo "✅ Created dashboard/.env.local"

echo ""
echo "✅ All .env files created!"
echo ""
echo "⚠️  IMPORTANT: Edit executor/.env and replace YOUR_GEMINI_API_KEY_HERE with your actual Gemini API key"
echo "   Get your API key from: https://aistudio.google.com/apikey"
echo ""
