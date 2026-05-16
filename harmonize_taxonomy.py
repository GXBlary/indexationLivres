import json
import os
import re

def pascal_case(s):
    # Split by dots, then capitalize each part
    parts = s.split('.')
    new_parts = []
    for p in parts:
        # Capitalize and handle multiple words
        words = re.findall(r'[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z0-9]|\b)', p)
        if not words: # Fallback for edge cases
            new_parts.append(p.strip().capitalize())
            continue
        new_parts.append(" ".join(w.capitalize() for w in words))
    return ".".join(new_parts)

def singulize(s):
    # Very light lemmatization: remove trailing 's' unless it's 'ss'
    parts = s.split('.')
    new_parts = []
    for p in parts:
        if p.endswith('s') and not p.endswith('ss') and len(p) > 3:
            # Check for common plurals to singular mapping
            if p.endswith('ies'):
                new_parts.append(p[:-3] + 'y')
            elif p.endswith('es') and not any(p.endswith(x) for x in ['sse', 'ce', 'ze']):
                new_parts.append(p[:-2])
            else:
                new_parts.append(p[:-1])
        else:
            new_parts.append(p)
    return ".".join(new_parts)

def harmonize(file_path):
    if not os.path.exists(file_path):
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)
    
    new_mapping = {}

    # User specific leaf rules
    LEAF_RULES = {
        "Leadership 4.0": "Technology.Digital Transformation.Leadership 4.0",
        "AgentOps": "Technology.Artificial Intelligence.AgentOps",
        "Agents": "Technology.Data.Agents",
        "Clustering": "Data Mining.Data Analysis.Clustering",
        "Graph Neural Networks": "Technology.Artificial Intelligence.Graph Neural Networks",
        "Metadata": "Technology.Data.Metadata",
        "Organizational Agility": "Management.Organizational Theory.Organizational Agility",
        "Site Reliability Engineering": "Technology.Software Engineering.Site Reliability Engineering",
        "Text Mining": "Science.Linguistics.Computational Linguistics.Natural Language Processing.Text Mining",
    }

    POLYSEMIC = ["Strategy", "Technological Advancement", "Transformation", "Resource Configuration", "Mitigation", "Optimization"]

    for tag, path in mapping.items():
        # 1. Standardize AI
        path = path.replace("AI.", "Artificial Intelligence.").replace("Ai.", "Artificial Intelligence.")
        if path.endswith(".AI") or path.endswith(".Ai"):
            path = path[:-2] + "Artificial Intelligence"
        
        # 2. PascalCase & Singularization
        path = pascal_case(path)
        path = singulize(path)

        # 3. Decision making (No work.)
        path = path.replace("Work.Decision Making", "Decision Making")

        # 3b. Remove duplicate adjacent segments (e.g., A.B.B -> A.B)
        dedup_parts = []
        for p in path.split('.'):
            if not dedup_parts or p != dedup_parts[-1]:
                dedup_parts.append(p)
        path = ".".join(dedup_parts)

        # 4. Handle Leaf conflicts according to user rules
        leaf = path.split('.')[-1]
        if leaf in LEAF_RULES:
            path = LEAF_RULES[leaf]
        
        # 5. Handle Polysemic / Low value (Maybe move to more context?)
        # For now, if the path is JUST one of these, it's problematic.
        # Use simple logic: if it's too general, prepend "General." or similar?
        # User said "Too polysemic". I will mark them for refinement or leave them if they are deep.
        # Actually, let's keep them if they have parents.
        
        # 6. Final Clean: "Artificial Intelligence" canonical
        path = path.replace("Ai ", "Artificial Intelligence ").replace(" AI", " Artificial Intelligence")

        new_mapping[tag] = path

    # Sort final mapping
    sorted_mapping = {k: new_mapping[k] for k in sorted(new_mapping.keys())}
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(sorted_mapping, f, indent=4, ensure_ascii=False)
    
    print("Harmonization complete.")

if __name__ == "__main__":
    harmonize("tag_mapping.json")
