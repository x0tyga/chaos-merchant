#!/bin/bash

set -e

echo "🚀 Chaos Merchant Setup"
echo "======================="

# Check Python version
python3 --version

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
echo "📦 Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  ffmpeg not found. Please install it:"
    echo "   macOS: brew install ffmpeg"
    echo "   Linux: sudo apt-get install ffmpeg"
    echo "   Windows: choco install ffmpeg"
else
    echo "✓ ffmpeg found"
fi

# Initialize database directory
mkdir -p data
mkdir -p input
mkdir -p output

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your API keys"
else
    echo "✓ .env already exists"
fi

# Initialize SQLite database
echo "📦 Initializing database..."
python3 -c "
import sqlite3
import os
db_path = 'data/chaos_merchant.db'
if not os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.close()
    print(f'✓ Database initialized: {db_path}')
else:
    print(f'✓ Database already exists: {db_path}')
"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your API keys"
echo "2. Run: source venv/bin/activate"
echo "3. Run: python main.py"
