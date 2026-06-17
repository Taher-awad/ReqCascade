import numpy as np
import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

class SemanticValidator:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            logger.info("Initializing Dense Vector Embedding Model (all-MiniLM-L6-v2) on CPU...")
            cls._instance = super(SemanticValidator, cls).__new__(cls)
            cls._instance.model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Model all-MiniLM-L6-v2 successfully loaded into memory.")
        return cls._instance

    def calculate_trace_score(self, source_requirement: str, generated_text: str) -> float:
        """
        Takes the atomic source requirement and the LLM's generated artifact,
        embeds both into dense mathematical vectors, and measures their Cosine Similarity.
        """
        # Return cleanly if either input is dead
        if not source_requirement or not generated_text:
            return 0.0

        try:
            embeddings = self.model.encode([source_requirement, generated_text])
            
            vector_a = embeddings[0]
            vector_b = embeddings[1]
            
            dot_product = np.dot(vector_a, vector_b)
            norm_a = np.linalg.norm(vector_a)
            norm_b = np.linalg.norm(vector_b)
            
            # Anti-div/0 guardrail
            if norm_a == 0 or norm_b == 0:
                return 0.0
                
            similarity = dot_product / (norm_a * norm_b)
            
            return max(0.0, min(1.0, float(similarity)))
            
        except Exception as e:
            logger.error(f"Semantic Validation Crash: {e}")
            return 0.0

# Singleton global instance so it builds tensor flow exactly once on server initialization
semantic_validator = SemanticValidator()
