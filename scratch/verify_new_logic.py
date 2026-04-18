import json
import os
from indexer import align_single_tag, load_json

if __name__ == "__main__":
    # Test terms
    terms = ["Cybernetics", "Philosophy", "Deep Learning", "Machine Learning"]
    
    print("--- Verification of Hierarchical Alignment ---")
    for t in terms:
        result = align_single_tag(t)
        print(f"Term: {t} => Hierarchy: {result}")
    
    # Generate the initial mindmap with current data
    print("\n--- Generating Taxonomy Mindmap ---")
    os.system("python visualize_taxonomy.py")
