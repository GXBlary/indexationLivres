import json
import os
from collections import defaultdict

def analyze_consistency(file_path):
    if not os.path.exists(file_path):
        print(f"File {file_path} not found.")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    report = []
    report.append("# Taxonomy Consistency Report\n")

    # 1. Leaf Conflicts (Same concept, different branches)
    leaf_to_paths = defaultdict(set)
    for tag, path in mapping.items():
        parts = path.split('.')
        leaf = parts[-1].lower() # Insensible à la casse
        leaf_to_paths[leaf].add(path)

    conflicts = {k: v for k, v in leaf_to_paths.items() if len(v) > 1}
    
    if conflicts:
        report.append("## Leaf Conflicts (Same leaf, different paths)")
        report.append("These concepts appear in multiple tree locations. Consider merging them.\n")
        for leaf, paths in sorted(conflicts.items()):
            report.append(f"### {leaf}")
            for p in sorted(paths):
                report.append(f"- {p}")
            report.append("")
    
    # 2. Parent Naming Inconsistencies (Casing / Abbreviations)
    all_segments = set()
    for path in mapping.values():
        for part in path.split('.'):
            all_segments.add(part)
    
    segment_case_map = defaultdict(set)
    for seg in all_segments:
        segment_case_map[seg.lower()].add(seg)
    
    casing_issues = {k: v for k, v in segment_case_map.items() if len(v) > 1}
    if casing_issues:
        report.append("## Casing & Naming Inconsistencies")
        report.append("Identical segments with different casing or punctuation found.\n")
        for lower_seg, variations in sorted(casing_issues.items()):
            report.append(f"- **{lower_seg}**: {', '.join(sorted(variations))}")
        report.append("")

    # 3. Path Depth Statistics
    lengths = [len(v.split('.')) for v in mapping.values()]
    if lengths:
        report.append("## Depth Statistics")
        report.append(f"- **Total Tags**: {len(mapping)}")
        report.append(f"- **Max Depth**: {max(lengths)}")
        report.append(f"- **Avg Depth**: {sum(lengths)/len(lengths):.2f}")
        
        deep_tags = {k: v for k, v in mapping.items() if len(v.split('.')) > 5}
        if deep_tags:
            report.append("\n### Outliers (> 5 segments)")
            for k, v in sorted(deep_tags.items())[:20]: # Limit report size
                report.append(f"- {k}: {v}")
            if len(deep_tags) > 20:
                report.append(f"- ... and {len(deep_tags)-20} more.")

    # 4. Canonical "Artificial Intelligence" Check
    ai_variants = [s for s in all_segments if s.lower() in ['ai', 'ais', 'artificial intelligence']]
    if any(v.lower() != 'artificial intelligence' for v in ai_variants):
        report.append("\n## Canonical Naming Conflicts")
        report.append(f"- Found non-canonical AI variants: {', '.join(ai_variants)}")

    with open("consistency_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    
    print(f"Report generated: consistency_report.md")

if __name__ == "__main__":
    analyze_consistency("tag_mapping.json")
