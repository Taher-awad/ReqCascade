import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Importing SemanticValidator...")
try:
    from validator import semantic_validator
    logger.info("Initializing MiniLM-L6-v2 embedder. This will fetch model weights if not locally cached.")
    score = semantic_validator.calculate_trace_score("Testing local download", "Testing local download")
    logger.info(f"Model successfully evaluated inference with dummy score: {score}")
except Exception as e:
    logger.error(f"Failed to bootstrap semantic_validator: {e}")
