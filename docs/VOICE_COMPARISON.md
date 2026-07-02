# Voice Quality Comparison: Kokoro vs ElevenLabs

## Overview

Step 4 of Chaos Merchant implements full support for both Kokoro TTS (free, local) and ElevenLabs (paid, cloud) to support an informed decision on primary voice engine.

## Architecture

### Kokoro TTS (Primary Candidate)

**Status:** Production-ready (Apache 2.0 license)
**Cost:** $0/month
**Hardware:** Runs on CPU only (Intel i3 compatible)
**Processing Time:** ~2-3 minutes per 7-short batch

**Characteristics:**
- Free and open-source
- Local processing (no API calls)
- 82M parameters (~327 MB model)
- Multiple voices available (Bella, Heart, Nova, etc)
- Consistent, neutral narration quality
- Good for energy-based gaming content

**Limitations:**
- May sound "flat" on dramatic/emotional content
- Voice selection limited vs ElevenLabs
- Requires local FFmpeg/librosa dependencies

### ElevenLabs (Fallback/Premium)

**Status:** Production-ready (established API)
**Cost:** $22/month (Creator plan, 121k chars)
**Hardware:** Cloud-based (no local requirements)
**Processing Time:** ~2-3 minutes per 7-short batch (batched API calls)

**Characteristics:**
- High-quality, natural-sounding voices
- 4,000+ available voices
- Excellent emotional expressiveness
- Industry standard for professional voiceovers
- Proven reliability and consistency

**Limitations:**
- Paid service ($22/month minimum)
- Requires API key and internet connection
- Quota-based billing system

## Quality Comparison Framework

### Test Scenarios

Three test cases to evaluate quality across different script types:

1. **Short Energetic Hook** (10-15 seconds)
2. **Medium Narrative** (20-30 seconds)
3. **Full Script** (40-50 seconds)

## Recommended: HYBRID APPROACH (80/20)

**Primary: Kokoro (80%)** - Free, acceptable quality
**Fallback: ElevenLabs (20%)** - Premium/dramatic content

**Cost:** $2-5/month (saves $17-20/month)

## Testing Instructions

Run voice comparison test:
```bash
python test_voice_comparison.py
```

This generates samples and comparison report in `data/voice_tests/`

---

**Status:** Step 4 ready for quality decision
