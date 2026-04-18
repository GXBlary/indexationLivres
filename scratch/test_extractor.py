import sys
import json
sys.path.append('.')
from indexer import get_metadata_from_llm

sample_text = """
The Self-Evolving Memory System: Adaptive Architectures for Artificial Agents.
By Dr. Alan Turing and Dr. Ada Lovelace.

Abstract:
This paper introduces a novel framework for self-evolving memory in LLM architectures,
allowing them to dynamically adapt and modify their internal graph databases across
various interactions without user intervention.
Keywords: Prompt Sensitivity, Agentic Framework, Graph Mem.
"""

print("--- Testing PDF metadata extraction with the current LLM_BACKEND ---")
titre, auteur, resume, mots_cles = get_metadata_from_llm(sample_text)
print(f"\nTitre: {titre}\nAuteur: {auteur}\nResume: {resume}\nMots Cles: {list(mots_cles)}")
