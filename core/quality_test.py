"""
Quality Testing Module - Compare Kokoro vs ElevenLabs voice quality
Used in Step 4 to make informed decision on primary voice engine
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from agents.script_voiceover import VoiceoverComparison, ScriptGenerator

logger = logging.getLogger(__name__)


class VoiceQualityTest:
    """Test and compare voice synthesis quality"""

    def __init__(self, output_dir='./data/voice_tests'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def test_sample(self, text, sample_name='test'):
        """
        Generate test sample with both engines
        
        Args:
            text: Text to synthesize
            sample_name: Name for test files
        
        Returns:
            dict: Test results with file paths
        """
        logger.info(f"🧪 Running voice quality test: {sample_name}")
        
        comparison = VoiceoverComparison.compare(text, sample_name)
        
        # Save comparison metadata
        metadata_path = self.output_dir / f"{sample_name}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(comparison, f, indent=2)
        
        logger.info(f"✓ Test results saved to {metadata_path}")
        
        return {
            'test_name': sample_name,
            'results': comparison,
            'metadata_path': str(metadata_path)
        }

    def run_full_comparison(self):
        """
        Run comprehensive voice quality comparison
        Tests across multiple scenarios
        """
        logger.info("🧪 Running full voice quality comparison...")
        
        test_cases = [
            {
                'name': 'short_energetic',
                'text': 'OMG THIS GLITCH IS INSANE! Watch this!',
                'description': 'Short, high-energy hook'
            },
            {
                'name': 'medium_narrative',
                'text': 'I found the craziest exploit in the game. It actually broke the entire level. Check out what happens when I trigger this specific sequence.',
                'description': 'Medium-length narrative'
            },
            {
                'name': 'long_full_script',
                'text': 'NO WAY THIS GLITCH JUST BROKE THE ENTIRE GAME! I found the craziest exploit and it actually sequence-broke the level. Watch what happens when I trigger this specific sequence. The developers probably never intended this to happen. If you want to see more broken games, drop a like and subscribe to the channel!',
                'description': 'Full 45-second script'
            }
        ]
        
        results = []
        for test_case in test_cases:
            logger.info(f"  Testing: {test_case['description']}")
            result = self.test_sample(test_case['text'], test_case['name'])
            results.append({
                'test_case': test_case,
                'result': result
            })
        
        # Save comparison report
        report_path = self.output_dir / 'comparison_report.json'
        report = {
            'timestamp': datetime.now().isoformat(),
            'tests': results,
            'summary': self._generate_summary(results)
        }
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"✓ Comparison report saved to {report_path}")
        
        return report

    def _generate_summary(self, results):
        """Generate quality comparison summary"""
        summary = {
            'kokoro': {
                'status': 'unknown',
                'availability': False,
                'quality_notes': []
            },
            'elevenlabs': {
                'status': 'unknown',
                'availability': False,
                'quality_notes': []
            }
        }
        
        for result in results:
            comparison = result['result']['results']
            
            if comparison.get('kokoro', {}).get('status') == 'success':
                summary['kokoro']['availability'] = True
                summary['kokoro']['status'] = 'available'
                summary['kokoro']['quality_notes'].append(f"Generated: {result['test_case']['description']}")
            
            if comparison.get('elevenlabs', {}).get('status') == 'success':
                summary['elevenlabs']['availability'] = True
                summary['elevenlabs']['status'] = 'available'
                summary['elevenlabs']['quality_notes'].append(f"Generated: {result['test_case']['description']}")
        
        return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    tester = VoiceQualityTest()
    report = tester.run_full_comparison()
    print(json.dumps(report, indent=2))
