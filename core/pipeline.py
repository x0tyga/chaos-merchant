"""
Core Pipeline - Main orchestration engine for Chaos Merchant
Sequences agents 1-9 in order with checkpoint/recovery system
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class PipelineStep(Enum):
    """Pipeline execution steps"""
    CLIP_INTELLIGENCE = 1
    SCRIPT_VOICEOVER = 2
    SEO_OPTIMIZER = 3
    VIDEO_PRODUCTION = 4
    THUMBNAIL = 5
    QUALITY_CONTROL = 6
    OUTPUT_PACKAGING = 7


class PipelineCheckpoint:
    """Manages checkpoint and recovery data"""
    
    def __init__(self, video_path, checkpoint_dir='./data/checkpoints'):
        self.video_path = Path(video_path)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / f"{self.video_path.stem}_checkpoint.json"

    def save(self, step, data):
        """Save checkpoint data"""
        checkpoint = {
            'timestamp': datetime.now().isoformat(),
            'video_path': str(self.video_path),
            'last_completed_step': step.value,
            'step_name': step.name,
            'data': data
        }
        with open(self.checkpoint_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        logger.info(f"💾 Checkpoint saved: {step.name}")

    def load(self):
        """Load checkpoint data"""
        if not self.checkpoint_file.exists():
            return None
        
        with open(self.checkpoint_file, 'r') as f:
            checkpoint = json.load(f)
        logger.info(f"📂 Checkpoint loaded: {checkpoint['step_name']}")
        return checkpoint

    def clear(self):
        """Clear checkpoint (video processing complete)"""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            logger.info("🧹 Checkpoint cleared")


class Pipeline:
    """Main pipeline orchestrator"""

    def __init__(self, video_path, data_dir='./data'):
        self.video_path = Path(video_path)
        self.data_dir = Path(data_dir)
        self.checkpoint = PipelineCheckpoint(video_path)
        self.processing_log = {
            'video_path': str(video_path),
            'started_at': datetime.now().isoformat(),
            'steps': {}
        }

    def log_step(self, step, status, details=None):
        """Log step execution"""
        self.processing_log['steps'][step.name] = {
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'details': details or {}
        }
        logger.info(f"📊 Step {step.name}: {status}")

    def should_recover(self):
        """Check if recovery is needed"""
        checkpoint = self.checkpoint.load()
        return checkpoint is not None

    def get_recovery_step(self):
        """Get the step to resume from"""
        checkpoint = self.checkpoint.load()
        if checkpoint:
            return PipelineStep(checkpoint['last_completed_step'] + 1)
        return PipelineStep.CLIP_INTELLIGENCE

    def run(self):
        """
        Execute the complete pipeline
        
        Returns:
            dict: Processing results
        """
        logger.info(f"🎬 Starting pipeline for: {self.video_path.name}")
        
        # Check for recovery
        if self.should_recover():
            recovery_step = self.get_recovery_step()
            logger.warning(f"⚠️  Recovering from checkpoint. Resuming at: {recovery_step.name}")
        
        try:
            # Step 1: Clip Intelligence
            logger.info("Step 1/7: Clip Intelligence Analysis")
            self.log_step(PipelineStep.CLIP_INTELLIGENCE, 'pending')
            # Placeholder: actual clip analysis will be implemented in Step 3
            self.checkpoint.save(PipelineStep.CLIP_INTELLIGENCE, {})
            self.log_step(PipelineStep.CLIP_INTELLIGENCE, 'complete')
            
            # Step 2: Script + Voiceover
            logger.info("Step 2/7: Script Generation + Voiceover")
            self.log_step(PipelineStep.SCRIPT_VOICEOVER, 'pending')
            # Placeholder: actual script generation will be implemented in Step 4
            self.checkpoint.save(PipelineStep.SCRIPT_VOICEOVER, {})
            self.log_step(PipelineStep.SCRIPT_VOICEOVER, 'complete')
            
            # Step 3: SEO Optimizer
            logger.info("Step 3/7: SEO Optimization")
            self.log_step(PipelineStep.SEO_OPTIMIZER, 'pending')
            # Placeholder: actual SEO generation will be implemented in Step 5
            self.checkpoint.save(PipelineStep.SEO_OPTIMIZER, {})
            self.log_step(PipelineStep.SEO_OPTIMIZER, 'complete')
            
            # Step 4: Video Production
            logger.info("Step 4/7: Video Production")
            self.log_step(PipelineStep.VIDEO_PRODUCTION, 'pending')
            # Placeholder: actual video production will be implemented in Step 6
            self.checkpoint.save(PipelineStep.VIDEO_PRODUCTION, {})
            self.log_step(PipelineStep.VIDEO_PRODUCTION, 'complete')
            
            # Step 5: Thumbnail Generation
            logger.info("Step 5/7: Thumbnail Generation")
            self.log_step(PipelineStep.THUMBNAIL, 'pending')
            # Placeholder: actual thumbnail generation will be implemented in Step 7
            self.checkpoint.save(PipelineStep.THUMBNAIL, {})
            self.log_step(PipelineStep.THUMBNAIL, 'complete')
            
            # Step 6: Quality Control
            logger.info("Step 6/7: Quality Control")
            self.log_step(PipelineStep.QUALITY_CONTROL, 'pending')
            # Placeholder: actual QC will be implemented in Step 8
            self.checkpoint.save(PipelineStep.QUALITY_CONTROL, {})
            self.log_step(PipelineStep.QUALITY_CONTROL, 'complete')
            
            # Step 7: Output Packaging
            logger.info("Step 7/7: Output Packaging")
            self.log_step(PipelineStep.OUTPUT_PACKAGING, 'pending')
            # Placeholder: actual output packaging will be implemented in Step 9
            self.checkpoint.save(PipelineStep.OUTPUT_PACKAGING, {})
            self.log_step(PipelineStep.OUTPUT_PACKAGING, 'complete')
            
            # Pipeline complete
            logger.info("✅ Pipeline complete!")
            self.checkpoint.clear()
            self.processing_log['completed_at'] = datetime.now().isoformat()
            self.processing_log['status'] = 'success'
            
            return {
                'status': 'success',
                'video_path': str(self.video_path),
                'processing_log': self.processing_log
            }
            
        except Exception as e:
            logger.error(f"❌ Pipeline failed: {e}")
            self.processing_log['status'] = 'failed'
            self.processing_log['error'] = str(e)
            raise


def run_pipeline(video_path):
    """
    Convenience function to run the pipeline
    
    Args:
        video_path: Path to video file
    
    Returns:
        dict: Pipeline results
    """
    pipeline = Pipeline(video_path)
    return pipeline.run()
