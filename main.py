#!/usr/bin/env python3
"""
Chaos Merchant - Autonomous YouTube Shorts Production System
Main entry point for the application
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def verify_environment():
    """Verify required environment variables and dependencies"""
    required_vars = ['ANTHROPIC_API_KEY', 'YOUTUBE_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please update your .env file")
        return False
    
    # Verify directories
    for directory in ['input', 'output', 'data']:
        Path(directory).mkdir(exist_ok=True)
    
    logger.info("✓ Environment verification passed")
    return True

def main():
    """Main entry point"""
    logger.info("Starting Chaos Merchant...")
    
    if not verify_environment():
        sys.exit(1)
    
    logger.info("✓ System ready")
    logger.info("Step 1 (Repo Scaffold) complete!")
    logger.info("Ready for Step 2: Watcher Agent")

if __name__ == "__main__":
    main()
