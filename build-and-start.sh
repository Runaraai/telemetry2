#!/bin/bash
# Build and start Omniference services

set -e

echo "🚀 Building and starting Omniference..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env file. Please edit it with your configuration."
    else
        echo "❌ .env.example not found. Please create .env manually."
        exit 1
    fi
fi

# Check for docker-compose or docker compose
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo "❌ docker-compose not found. Installing..."
    echo "Please install docker-compose:"
    echo "  sudo apt-get update && sudo apt-get install docker-compose"
    echo "  OR"
    echo "  sudo pip3 install docker-compose"
    exit 1
fi

# Check Docker permissions
if ! $COMPOSE_CMD ps &> /dev/null; then
    echo "⚠️  Docker permission issue detected."
    echo "Trying with sudo..."
    COMPOSE_CMD="sudo $COMPOSE_CMD"
fi

echo "📦 Building Docker images..."
$COMPOSE_CMD build

echo "🚀 Starting services..."
$COMPOSE_CMD up -d

echo "✅ Done! Services are starting..."
echo ""
echo "To view logs:"
echo "  $COMPOSE_CMD logs -f"
echo ""
echo "To stop services:"
echo "  $COMPOSE_CMD down"
echo ""
echo "To check status:"
echo "  $COMPOSE_CMD ps"




