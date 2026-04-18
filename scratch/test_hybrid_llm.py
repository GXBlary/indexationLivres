import sys
sys.path.append('.')
from scratch.indexer_new import align_single_tag, tag_mapping

tags_to_test = [
    "agentic framework",
    "multimodal rag",
    "enterprise-grade systems"
]

for tag in tags_to_test:
    # Remove from cache if exists flat to force evaluation
    if tag in tag_mapping and "." not in tag_mapping[tag]:
        del tag_mapping[tag]

    print(f"\n--- Testing alignment for '{tag}' ---")
    result = align_single_tag(tag)
    print(f"Result: {result}")
