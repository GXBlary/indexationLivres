import json
import os

TAG_MAPPING_FILE = "tag_mapping.json"
TAG_LIST_FILE = "tag_list.json"
OUTPUT_FILE = "taxonomy_mindmap.html"

def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def build_tree(mapping):
    root = {"name": "Taxonomy Root", "children": []}
    
    def find_or_create(parent_node, name):
        if "children" not in parent_node:
            parent_node["children"] = []
        for child in parent_node["children"]:
            if child["name"] == name:
                return child
        new_node = {"name": name}
        parent_node["children"].append(new_node)
        return new_node

    for raw_tag, hierarchy in mapping.items():
        if not isinstance(hierarchy, str):
            continue
            
        parts = hierarchy.split('.')
        current = root
        for part in parts:
            current = find_or_create(current, part)
            
    return root

def generate_html(data):
    json_data = json.dumps(data, indent=2)
    
    # Use simple replacement instead of f-string to avoid complex escaping of CSS/JS braces
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Taxonomy Mindmap</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📚</text></svg>">
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            overflow: hidden;
            background-color: #f8f9fa;
        }
        .node circle {
            fill: #fff;
            stroke: #3498db;
            stroke-width: 2px;
            cursor: pointer;
        }
        .node text {
            font-size: 12px;
            fill: #2c3e50;
        }
        .link {
            fill: none;
            stroke: #bdc3c7;
            stroke-width: 1.5px;
        }
        #controls {
            position: absolute;
            top: 20px;
            left: 20px;
            z-index: 10;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h1 {
            margin: 0 0 10px 0;
            font-size: 18px;
            color: #2c3e50;
        }
        input {
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            width: 200px;
        }
    </style>
</head>
<body>
    <div id="controls">
        <h1>Taxonomy Drill-down</h1>
        <input type="text" id="search" placeholder="Search tag...">
        <p style="font-size: 11px; color: #7f8c8d; margin-top: 10px;">
            Scroll to zoom | Drag to pan | Click nodes to expand
        </p>
    </div>
    <svg id="canvas"></svg>

    <script>
        const data = {{JSON_DATA}};
        let i = 0;

        const width = window.innerWidth;
        const height = window.innerHeight;
        const margin = {top: 20, right: 120, bottom: 20, left: 120};

        const svg = d3.select("#canvas")
            .attr("width", width)
            .attr("height", height)
            .call(d3.zoom().on("zoom", (event) => {
                g.attr("transform", event.transform);
            }))
            .append("g");

        const g = svg.append("g")
            .attr("transform", `translate(${margin.left}, ${margin.top})`);

        const tree = d3.tree().nodeSize([30, 200]);
        let root = d3.hierarchy(data, d => d.children);

        root.x0 = height / 2;
        root.y0 = 0;

        // Function to collapse nodes
        function collapse(d) {
            if (d.children) {
                d._children = d.children;
                d._children.forEach(collapse);
                d.children = null;
            }
        }

        // Initially collapse all except root
        if (root.children) {
            root.children.forEach(collapse);
        }

        update(root);

        function update(source) {
            const nodes = root.descendants().reverse();
            const links = root.links();

            tree(root);

            let left = root;
            let right = root;
            root.eachBefore(node => {
                if (node.x < left.x) left = node;
                if (node.x > right.x) right = node;
            });

            const transition = svg.transition().duration(750);

            const node = g.selectAll("g.node")
                .data(nodes, d => d.id || (d.id = ++i));

            const nodeEnter = node.enter().append("g")
                .attr("class", "node")
                .attr("transform", d => `translate(${source.y0}, ${source.x0})`)
                .on("click", (event, d) => {
                    if (d.children) {
                        d._children = d.children;
                        d.children = null;
                    } else {
                        d.children = d._children;
                        d._children = null;
                    }
                    update(d);
                });

            nodeEnter.append("circle")
                .attr("r", 1e-6)
                .style("fill", d => d._children ? "#3498db" : "#fff");

            nodeEnter.append("text")
                .attr("dy", ".35em")
                .attr("x", d => d._children || d.children ? -13 : 13)
                .attr("text-anchor", d => d._children || d.children ? "end" : "start")
                .text(d => d.data.name);

            const nodeUpdate = node.merge(nodeEnter).transition(transition)
                .attr("transform", d => `translate(${d.y}, ${d.x})`);

            nodeUpdate.select("circle")
                .attr("r", 6)
                .style("fill", d => d._children ? "#3498db" : "#fff");

            nodeUpdate.select("text")
                .style("fill-opacity", 1);

            const nodeExit = node.exit().transition(transition)
                .attr("transform", d => `translate(${source.y}, ${source.x})`)
                .remove();

            nodeExit.select("circle")
                .attr("r", 1e-6);

            nodeExit.select("text")
                .style("fill-opacity", 1e-6);

            const link = g.selectAll("path.link")
                .data(links, d => d.target.id);

            const linkEnter = link.enter().insert("path", "g")
                .attr("class", "link")
                .attr("d", d => {
                    const o = {x: source.x0, y: source.y0};
                    return diagonal(o, o);
                });

            const linkUpdate = link.merge(linkEnter).transition(transition)
                .attr("d", d => diagonal(d.source, d.target));

            const linkExit = link.exit().transition(transition)
                .attr("d", d => {
                    const o = {x: source.x, y: source.y};
                    return diagonal(o, o);
                })
                .remove();

            nodes.forEach(d => {
                d.x0 = d.x;
                d.y0 = d.y;
            });

            function diagonal(s, t) {
                return `M ${s.y} ${s.x}
                        C ${(s.y + t.y) / 2} ${s.x},
                          ${(s.y + t.y) / 2} ${t.x},
                          ${t.y} ${t.x}`;
            }
        }
    </script>
</body>
</html>
"""
    return html_template.replace("{{JSON_DATA}}", json_data)

if __name__ == "__main__":
    print(f"-> Chargement de {TAG_MAPPING_FILE}...")
    mapping = load_json(TAG_MAPPING_FILE, {})
    print(f"-> Construction de l'arbre ({len(mapping)} entrées)...")
    tree_data = build_tree(mapping)
    print(f"-> Génération du HTML...")
    html_content = generate_html(tree_data)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"-> Succès ! Mindmap générée dans : {OUTPUT_FILE}")
