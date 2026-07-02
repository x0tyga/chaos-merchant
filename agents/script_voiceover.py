"""
Script + Voiceover Agent - Script generation and voice synthesis
Generates gaming-focused scripts and produces voiceover audio
Supports Kokoro TTS (primary) and ElevenLabs (fallback/comparison)
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from datetime import datetime
import tempfile

from anthropic import Anthropic

logger = logging.getLogger(__name__)


class ScriptGenerator:
    """Generates YouTube Shorts scripts using Claude API"""

    def __init__(self):
        self.client = Anthropic()

    def generate_script(self, clip_data, trending_topics=None, channel_history=None):
        """
        Generate voiceover script from clip data
        
        Args:
            clip_data: Clip intelligence manifest
            trending_topics: List of trending topics
            channel_history: Previous video summaries
        
        Returns:
            dict: Generated script with metadata
        """
        logger.info("📝 Generating script...")
        
        # Build context
        top_clips = clip_data.get('top_clips', [])[:3]  # Use top 3 for context
        
        prompt = f"""Generate a YouTube Shorts voiceover script.

Video data:
- Duration: {clip_data.get('duration', 0):.1f} seconds
- Number of clips: {len(clip_data.get('clips', []))}
- Top engagement scores: {[round(c.get('engagement_score', 0), 2) for c in top_clips]}

Trending topics: {json.dumps(trending_topics or [], indent=2)}
Channel history: {json.dumps(channel_history or [], indent=2)}

Generate a JSON object with: hook, main_content, cta, full_script, reading_time_seconds"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Parse response
            response_text = response.content[0].text
            
            # Try to extract JSON
            try:
                # Find JSON in response
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    script_data = json.loads(json_str)
                else:
                    raise ValueError("No JSON found")
            except (json.JSONDecodeError, ValueError):
                # Fallback: create structured script from response
                script_data = {
                    'hook': 'Check out this crazy moment!',
                    'main_content': response_text[:200],
                    'cta': 'Drop a like and subscribe for more!',
                    'full_script': response_text,
                    'reading_time_seconds': 40
                }
            
            logger.info(f"✓ Script generated ({script_data.get('reading_time_seconds', 0)}s)")
            return {
                'status': 'success',
                'script': script_data,
                'model': 'claude-3-5-haiku-20241022'
            }
            
        except Exception as e:
            logger.error(f"❌ Script generation failed: {e}")
            raise


class KokoroTTS:
    """Kokoro TTS voice synthesis (free, local)"""

    def __init__(self):
        self.available = self._check_availability()

    def _check_availability(self):
        """Check if Kokoro is available"""
        try:
            import kokoro
            return True
        except ImportError:
            logger.warning("⚠️  Kokoro not installed. Install with: pip install kokoro-tts")
            return False

    def generate(self, text, voice='bella', output_path=None):
        """
        Generate voiceover using Kokoro TTS
        
        Args:
            text: Text to synthesize
            voice: Voice name (bella, heart, nova, etc)
            output_path: Output MP3 file path
        
        Returns:
            dict: Audio file path and metadata
        """
        if not self.available:
            raise RuntimeError("Kokoro TTS not available")
        
        logger.info(f"🎙️  Generating voiceover with Kokoro ({voice})...")
        
        try:
            import kokoro
            
            if output_path is None:
                output_path = f"/tmp/voiceover_kokoro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            
            # Generate audio
            tts = kokoro.Kokoro(voice=voice)
            audio = tts.synthesize(text)
            
            # Save to file
            tts.save_audio(audio, output_path)
            
            logger.info(f"✓ Kokoro voiceover saved: {output_path}")
            
            return {
                'status': 'success',
                'engine': 'kokoro',
                'voice': voice,
                'audio_path': output_path,
                'text_length': len(text),
                'estimated_duration': len(text) / 150 * 60  # ~150 words per minute
            }
            
        except Exception as e:
            logger.error(f"❌ Kokoro TTS failed: {e}")
            raise


class ElevenLabsTTS:
    """ElevenLabs voice synthesis (paid, cloud-based)"""

    def __init__(self):
        self.api_key = os.getenv('ELEVENLABS_API_KEY')
        self.voice_id = os.getenv('ELEVENLABS_VOICE_ID')
        self.available = bool(self.api_key and self.voice_id)

    def generate(self, text, output_path=None):
        """
        Generate voiceover using ElevenLabs API
        
        Args:
            text: Text to synthesize
            output_path: Output MP3 file path
        
        Returns:
            dict: Audio file path and metadata
        """
        if not self.available:
            raise RuntimeError("ElevenLabs not configured (missing API key or voice ID)")
        
        logger.info(f"🎙️  Generating voiceover with ElevenLabs...")
        
        try:
            import requests
            
            if output_path is None:
                output_path = f"/tmp/voiceover_elevenlabs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
            
            # Call ElevenLabs API
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "xi-api-key": self.api_key,
                "Content-Type": "application/json"
            }
            data = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            
            response = requests.post(url, json=data, headers=headers)
            
            if response.status_code != 200:
                raise RuntimeError(f"ElevenLabs API error: {response.status_code}")
            
            # Save audio
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"✓ ElevenLabs voiceover saved: {output_path}")
            
            return {
                'status': 'success',
                'engine': 'elevenlabs',
                'voice_id': self.voice_id,
                'audio_path': output_path,
                'text_length': len(text),
                'estimated_duration': len(text) / 150 * 60
            }
            
        except Exception as e:
            logger.error(f"❌ ElevenLabs TTS failed: {e}")
            raise


class VoiceoverComparison:
    """Generates samples with both engines for comparison"""

    @staticmethod
    def compare(text, sample_name="comparison"):
        """
        Generate voiceover with both Kokoro and ElevenLabs
        
        Args:
            text: Text to synthesize
            sample_name: Name for comparison samples
        
        Returns:
            dict: Comparison results with file paths
        """
        results = {}
        
        # Kokoro
        kokoro = KokoroTTS()
        if kokoro.available:
            try:
                kokoro_path = f"/tmp/{sample_name}_kokoro.wav"
                result = kokoro.generate(text, output_path=kokoro_path)
                results['kokoro'] = result
                logger.info("✓ Kokoro sample generated")
            except Exception as e:
                logger.warning(f"Kokoro failed: {e}")
                results['kokoro'] = {'status': 'failed', 'error': str(e)}
        else:
            logger.warning("Kokoro not available")
            results['kokoro'] = {'status': 'unavailable'}
        
        # ElevenLabs
        elevenlabs = ElevenLabsTTS()
        if elevenlabs.available:
            try:
                elevenlabs_path = f"/tmp/{sample_name}_elevenlabs.mp3"
                result = elevenlabs.generate(text, output_path=elevenlabs_path)
                results['elevenlabs'] = result
                logger.info("✓ ElevenLabs sample generated")
            except Exception as e:
                logger.warning(f"ElevenLabs failed: {e}")
                results['elevenlabs'] = {'status': 'failed', 'error': str(e)}
        else:
            logger.warning("ElevenLabs not available")
            results['elevenlabs'] = {'status': 'unavailable'}
        
        return {
            'sample_name': sample_name,
            'text': text,
            'results': results,
            'timestamp': datetime.now().isoformat()
        }


def generate_voiceover(clip_data, primary_engine='kokoro', trending_topics=None, channel_history=None):
    """
    Main function to generate script and voiceover
    
    Args:
        clip_data: Clip intelligence manifest
        primary_engine: 'kokoro' or 'elevenlabs'
        trending_topics: Trending topics for context
        channel_history: Previous video data
    
    Returns:
        dict: Script + voiceover results
    """
    logger.info("🎬 Starting script + voiceover generation...")
    
    # Generate script
    generator = ScriptGenerator()
    script_result = generator.generate_script(clip_data, trending_topics, channel_history)
    
    if script_result['status'] != 'success':
        raise RuntimeError("Script generation failed")
    
    script = script_result['script']
    full_text = script.get('full_script', '')
    
    # Generate voiceover
    try:
        if primary_engine == 'kokoro':
            tts = KokoroTTS()
            if tts.available:
                voiceover_result = tts.generate(full_text)
            else:
                logger.warning("Kokoro unavailable, falling back to ElevenLabs")
                tts = ElevenLabsTTS()
                voiceover_result = tts.generate(full_text)
        else:
            tts = ElevenLabsTTS()
            if tts.available:
                voiceover_result = tts.generate(full_text)
            else:
                logger.warning("ElevenLabs unavailable, falling back to Kokoro")
                tts = KokoroTTS()
                voiceover_result = tts.generate(full_text)
    except Exception as e:
        logger.error(f"❌ Voiceover generation failed: {e}")
        raise
    
    return {
        'status': 'success',
        'script': script,
        'voiceover': voiceover_result,
        'timestamp': datetime.now().isoformat()
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    # Test comparison
    test_text = """NO WAY THIS GLITCH JUST BROKE THE ENTIRE GAME! 
    I found the craziest exploit and it actually sequence-broke the level. 
    Watch what happens when I trigger this specific sequence. 
    If you want to see more broken games, drop a like and subscribe!"""
    
    print("Testing voice comparison...")
    comparison = VoiceoverComparison.compare(test_text)
    print(json.dumps(comparison, indent=2))
