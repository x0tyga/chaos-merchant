#!/usr/bin/env python3
"""
Voice Quality Comparison Test
Tests both Kokoro and ElevenLabs to help choose primary voice engine

Usage:
  python test_voice_comparison.py
"""

import os
import sys
import logging
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import test module
from core.quality_test import VoiceQualityTest


def print_header(text):
    """Print formatted header"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def main():
    """Run voice quality comparison"""
    
    print_header("🎙️ VOICE QUALITY COMPARISON TEST")
    
    logger.info("Starting voice quality comparison...")
    logger.info("This tests both Kokoro and ElevenLabs for quality assessment\n")
    
    # Check environment
    kokoro_available = True
    try:
        import kokoro_onnx
    except ImportError:
        logger.warning("⚠️  kokoro-onnx not installed")
        logger.warning("   Install with: pip install kokoro-onnx")
        kokoro_available = False
    
    elevenlabs_available = bool(os.getenv('ELEVENLABS_API_KEY') and os.getenv('ELEVENLABS_VOICE_ID'))
    if not elevenlabs_available:
        logger.warning("⚠️  ElevenLabs not configured")
        logger.warning("   Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env")
    
    if not kokoro_available and not elevenlabs_available:
        logger.error("❌ Neither Kokoro nor ElevenLabs available")
        logger.error("Please install Kokoro or configure ElevenLabs")
        sys.exit(1)
    
    print_header("AVAILABLE ENGINES")
    print(f"✓ Kokoro TTS: {'Available' if kokoro_available else 'Not installed'}")
    print(f"✓ ElevenLabs: {'Configured' if elevenlabs_available else 'Not configured'}\n")
    
    # Run tests
    print_header("RUNNING TESTS")
    
    tester = VoiceQualityTest()
    
    try:
        report = tester.run_full_comparison()
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        sys.exit(1)
    
    # Print results
    print_header("TEST RESULTS")
    
    summary = report['summary']
    
    print("KOKORO TTS:")
    if summary['kokoro']['availability']:
        print("  ✓ Status: Available")
        print("  ✓ Quality: Local CPU processing, fast")
        print("  ✓ Cost: Free (open-source)")
        print("  ⚠️  Limitations: May sound robotic on some voices")
    else:
        print("  ✗ Status: Not available")
        print("  ✗ Error: Check installation")
    print()
    
    print("ELEVENLABS:")
    if summary['elevenlabs']['availability']:
        print("  ✓ Status: Available")
        print("  ✓ Quality: High-quality, natural voice")
        print("  ✓ Cost: $22/month Creator plan")
        print("  ✓ Advantages: Most natural, consistent")
    else:
        print("  ✗ Status: Not available")
        print("  ✗ Error: Check API configuration")
    print()
    
    # Recommendation
    print_header("RECOMMENDATION")
    
    if summary['kokoro']['availability'] and summary['elevenlabs']['availability']:
        print("✓ Both engines available - recommend HYBRID approach:")
        print("  1. Use Kokoro for 80% of shorts (free)")
        print("  2. Use ElevenLabs for premium/emotional content")
        print("  3. Test both in production to assess tradeoff")
    elif summary['kokoro']['availability']:
        print("✓ Kokoro available:")
        print("  - Use Kokoro as primary")
        print("  - Saves $22/month vs ElevenLabs")
        print("  - Quality acceptable for gaming content")
    elif summary['elevenlabs']['availability']:
        print("✓ ElevenLabs available:")
        print("  - Use ElevenLabs as primary")
        print("  - Higher quality for all shorts")
        print("  - Cost: $22/month (fixed budget)")
    
    print()
    print(f"✓ Test results saved to: data/voice_tests/comparison_report.json")
    print()


if __name__ == "__main__":
    main()
