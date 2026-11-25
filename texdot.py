#!/usr/bin/env python3
""" make pylint happy """
# pylint: disable=line-too-long,too-many-locals,too-many-statements,consider-using-with,too-many-branches
import os
import sys
import subprocess
import re
import html
import textwrap
import pydot

def sanitize_for_lualatex(tex_code: str) -> str:
    """
    Removes legacy 8-bit pdflatex encoding packages (inputenc / T1 fontenc)
    that corrupt characters like 'ß' -> 'SS' under LuaLaTeX.
    """
    tex_code = re.sub(r'\\usepackage\[[^\]]*\]\{inputenc\}\s*', '', tex_code)
    tex_code = re.sub(r'\\usepackage\[T1\]\{fontenc\}\s*', '', tex_code)
    return tex_code

def make_searchable_dot_label(latex_src: str, width: int = 55) -> str:
    """
    Extracts only the body inside \\begin{document}...\\end{document},
    wraps it, and escapes it for Graphviz.
    """
    if "\\begin{document}" in latex_src:
        latex_src = latex_src.split("\\begin{document}", 1)[1]
    if "\\end{document}" in latex_src:
        latex_src = latex_src.split("\\end{document}", 1)[0]

    compact = " ".join(latex_src.strip().split())
    wrapped_lines = textwrap.wrap(compact, width=width) or [""]

    escaped_lines = [
        line.replace("\\", "\\\\").replace('"', '\\"')
        for line in wrapped_lines
    ]
    return '"' + "\\n".join(escaped_lines) + '"'

def unquote(s):
    """Remove surrounding quotes from Graphviz attributes."""
    if s and s.startswith('"') and s.endswith('"'):
        return s[1:-1].replace('\\"', '"')
    return s

def write_if_changed(filepath, content):
    """Writes content to a file only if it differs from the existing file.
    This preserves modification timestamps for 'make' incremental compilation."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            existing_content = f.read()
        if existing_content == content:
            return False

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return True

def is_valid_linux_filename(filename):
    """Check if a string is a valid Linux filename (no slashes, no nulls, <= 255 bytes)."""
    if not filename or '/' in filename or '\0' in filename:
        return False
    if len(filename.encode('utf-8')) > 255:
        return False
    return True

def is_zathura_running() -> bool:
    """Check if a zathura process is already running."""
    try:
        res = subprocess.run(
            ["pgrep", "-x", "zathura"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
        return res.returncode == 0
    except FileNotFoundError:
        return False

def build_subgraph_dot(center_id, graph, node_map, processed_nodes, all_edges):
    """
    Builds a small pydot graph containing only center_id, its direct incoming/outgoing
    neighbors, and the edges incident to center_id. Reuses already-generated PNGs
    without searchable text layers.
    """
    strict_val = graph.obj_dict.get('strict', False)
    sub = pydot.Dot(graph_type=graph.get_type(), strict=strict_val)

    # Copy layout-relevant graph attributes (skip comment template, big title, and rankdir)
    for k, v in graph.get_attributes().items():
        if k not in ('comment', 'label', 'rankdir'):
            sub.set(k, v)
    sub.set('rankdir', 'LR')

    # Copy default node/edge attributes if present in the big graph
    for default_node in graph.get_node_defaults():
        attrs = default_node if isinstance(default_node, dict) else default_node.get_attributes()
        sub.set_node_defaults(**attrs)
    for default_edge in graph.get_edge_defaults():
        attrs = default_edge if isinstance(default_edge, dict) else default_edge.get_attributes()
        sub.set_edge_defaults(**attrs)

    # Collect incident edges and involved node IDs
    incident_edges = []
    involved_ids = {center_id}
    for edge in all_edges:
        src = unquote(edge.get_source())
        dst = unquote(edge.get_destination())
        if src == center_id or dst == center_id:
            incident_edges.append(edge)
            involved_ids.add(src)
            involved_ids.add(dst)

    # Add involved nodes with their visual attributes and PNG image only
    for nid in sorted(involved_ids):
        orig_node = node_map.get(nid)
        attrs = {}
        if orig_node is not None:
            for k, v in orig_node.get_attributes().items():
                if k not in ('comment', 'label', 'fontname', 'fontsize', 'fontcolor', 'URL'):
                    attrs[k] = v

        if nid in processed_nodes:
            attrs['image'] = f'"{processed_nodes[nid]}"'
            attrs['label'] = '""'
            if nid != center_id:
                # Relative link inside the same subdirectory
                attrs['URL'] = f'"sub_{nid}.pdf"'

        sub.add_node(pydot.Node(f'"{nid}"', **attrs))

    # Add incident edges preserving style (solid/dashed), color, etc.
    for edge in incident_edges:
        src = unquote(edge.get_source())
        dst = unquote(edge.get_destination())
        e_attrs = {
            k: v for k, v in edge.get_attributes().items()
            if k != 'comment'
        }
        sub.add_edge(pydot.Edge(f'"{src}"', f'"{dst}"', **e_attrs))

    return sub

def generate_latex_and_makefile(dot_file):
    """ Parse the .dot file """
    graphs = pydot.graph_from_dot_file(dot_file)
    if not graphs:
        print(f"Error: Could not parse {dot_file}")
        return
    graph = graphs[0]

    # Extract the LaTeX template from the graph's comment attribute
    graph_attrs = graph.get_attributes()
    template = unquote(graph_attrs.get('comment', ''))

    if not template or r'\begin{document}' not in template:
        print("Error: No valid LaTeX template found in the graph 'comment' attribute.")
        return

    # Sanitize template for LuaLaTeX compatibility (strips T1/inputenc conflicts)
    template = sanitize_for_lualatex(template)

    # Subdirectory for per-node neighborhood PDFs (dot filename without .dot)
    sub_dir = os.path.splitext(os.path.basename(dot_file))[0]
    os.makedirs(sub_dir, exist_ok=True)

    extracted_items = []
    updated_count = 0
    node_map = {}
    processed_nodes = {}  # base_name -> png_filename

    # Process all nodes
    for node in graph.get_nodes():
        raw_name = node.get_name()
        if raw_name in ('node', 'edge', 'graph', '"\\n"', '"\n"', '\\n', '\n'):
            continue

        base_name = unquote(raw_name)
        node_map[base_name] = node

        comment_attr = unquote(node.get('comment'))
        image_attr = unquote(node.get('image'))
        label_raw = node.get('label')

        if comment_attr:
            if image_attr:
                print(f"Error: Node '{raw_name}' contains both an 'image' attribute and a 'comment' attribute. The image attribute is now automatically generated.")
                sys.exit(1)
            if label_raw is not None:
                print(f"Error: Node '{raw_name}' contains both a 'label' attribute and a 'comment' attribute. No label is allowed if a comment attribute is present.")
                sys.exit(1)

            tex_filename = f"{base_name}.tex"
            png_filename = f"{base_name}.png"
            sub_pdf_name = f"sub_{base_name}.pdf"

            if not is_valid_linux_filename(tex_filename) or not is_valid_linux_filename(sub_pdf_name):
                print(f"Error: Node ID '{base_name}' produces invalid Linux filenames. Filenames cannot contain '/' or exceed 255 bytes.")
                sys.exit(1)

            tex_content = template.replace(r'\end{document}', f"{comment_attr}\n\\end{{document}}")

            if write_if_changed(tex_filename, tex_content):
                updated_count += 1

            extracted_items.append({'base': base_name, 'png': png_filename, 'tex': tex_filename})
            processed_nodes[base_name] = png_filename

            # Inject auto-generated image, searchable label, and link to subgraph PDF in sub_dir
            node.set('image', f'"{png_filename}"')
            node.set_label(make_searchable_dot_label(tex_content))
            node.set('fontname', '"Courier"')
            node.set('fontsize', '"5"')
            node.set('fontcolor', '"#00000001"')
            node.set('URL', f'"{sub_dir}/{sub_pdf_name}"')

    # Process all edges and inject the HTML label
    all_edges = graph.get_edges()
    for edge in all_edges:
        comment_attr = unquote(edge.get('comment'))
        image_attr = unquote(edge.get('image'))
        label_raw = edge.get('label')

        if comment_attr:
            source = unquote(edge.get_source())
            dest = unquote(edge.get_destination())

            if image_attr:
                print(f"Error: Edge from {source} to {dest} contains both an 'image' attribute and a 'comment' attribute. The image attribute is now automatically generated.")
                sys.exit(1)
            if label_raw is not None:
                print(f"Error: Edge from {source} to {dest} contains both a 'label' attribute and a 'comment' attribute. No label is allowed if a comment attribute is present.")
                sys.exit(1)

            base_name = f"{source}_{dest}"
            tex_filename = f"{base_name}.tex"
            png_filename = f"{base_name}.png"

            if not is_valid_linux_filename(tex_filename) or not is_valid_linux_filename(png_filename):
                print(f"Error: Edge from {source} to {dest} produces invalid Linux filenames ('{tex_filename}'). Filenames cannot contain '/' or exceed 255 bytes.")
                sys.exit(1)

            tex_content = template.replace(r'\end{document}', f"{comment_attr}\n\\end{{document}}")

            if write_if_changed(tex_filename, tex_content):
                updated_count += 1

            extracted_items.append({'base': base_name, 'png': png_filename, 'tex': tex_filename})

            # Auto-generate the HTML label for Graphviz edges
            body_tex = tex_content
            if "\\begin{document}" in body_tex:
                body_tex = body_tex.split("\\begin{document}", 1)[1]
            if "\\end{document}" in body_tex:
                body_tex = body_tex.split("\\end{document}", 1)[0]

            compact_edge = " ".join(body_tex.strip().split())
            wrapped_edge = "<BR/>".join(
                html.escape(line)
                for line in (textwrap.wrap(compact_edge, width=25) or [""])
            )

            html_label = (
                f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="0">'
                f'<TR><TD><IMG SRC="{png_filename}"/></TD></TR>'
                f'<TR><TD><FONT FACE="Courier" POINT-SIZE="5" COLOR="#00000001">{wrapped_edge}</FONT></TD></TR>'
                f'</TABLE>>'
            )
            edge.set_label(html_label)

    # --- NEW CLEANUP BLOCK TO FIX PYDOT BUG ---
    spurious_nodes = [node.get_name() for node in graph.get_nodes() if node.get_name() in ('"\\n"', '"\n"', '\\n', '\n')]
    for name in set(spurious_nodes):
        graph.del_node(name)
    # ------------------------------------------

    # Generate per-node neighborhood .dot files
    sub_pdfs = []
    sub_updated = 0
    for base_name in processed_nodes:
        sub_dot_file = f"sub_{base_name}.dot"
        sub_pdf_file = f"{sub_dir}/sub_{base_name}.pdf"
        sub_graph = build_subgraph_dot(base_name, graph, node_map, processed_nodes, all_edges)
        if write_if_changed(sub_dot_file, sub_graph.to_string()):
            sub_updated += 1
        sub_pdfs.append(sub_pdf_file)

    print(f"Extracted {len(extracted_items)} LaTeX definitions ({updated_count} newly written/updated).")
    print(f"Generated {len(sub_pdfs)} node neighborhood .dot files ({sub_updated} newly written/updated) -> {sub_dir}/")

    # Save the processed Graphviz model to a temporary file
    processed_dot_file = dot_file.replace('.dot', '_processed.dot')
    write_if_changed(processed_dot_file, graph.to_string())

    # Create the Makefile pointing to the temporary processed dot file and all subgraphs
    target_pdf = dot_file.replace('.dot', '.pdf')
    all_pngs = " ".join([item['png'] for item in extracted_items])
    all_sub_pdfs = " ".join(sub_pdfs)

    makefile_content = f"""# Auto-generated Makefile

ALL_PNGS = {all_pngs}

all: {target_pdf} {all_sub_pdfs}

# Final graph compilation depends on the processed .dot file and all generated .png labels
{target_pdf}: {processed_dot_file} $(ALL_PNGS)
\tdot -Tpdf {processed_dot_file} -o {target_pdf}

# Pattern rule: Compile each node's neighborhood .dot to .pdf inside {sub_dir}/
{sub_dir}/sub_%.pdf: sub_%.dot $(ALL_PNGS)
\tmkdir -p {sub_dir}
\tdot -Tpdf $< -o $@

# Pattern rule: Convert .pdf to cropped .png using pdftocairo
%.png: %.pdf
\tpdftocairo -singlefile -png -transp -r 120 $< $*

# Pattern rule: Compile .tex to .pdf using latexmk
%.pdf: %.tex
\tlatexmk -pdf -lualatex $<

clean:
\t-latexmk -c
\trm -f *.tex *.pdf *.png sub_*.dot {processed_dot_file} Makefile
\trm -rf {sub_dir}
"""

    write_if_changed('Makefile', makefile_content)

    # --- Automated Execution ---
    jobs = os.cpu_count() or 1
    print(f"Running make -j{jobs}...")
    try:
        subprocess.run(["make", f"-j{jobs}"], check=True)
        print(f"Successfully generated {target_pdf} and {len(sub_pdfs)} neighborhood PDFs in {sub_dir}/.")

        if not is_zathura_running():
            print(f"Opening {target_pdf} in zathura...")
            subprocess.Popen(["zathura", target_pdf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print(f"{target_pdf} updated (zathura will auto-reload).")

    except subprocess.CalledProcessError as e:
        print(f"Compilation failed during make execution: {e}")
    except FileNotFoundError:
        print("Error: Make or Zathura is not installed or not in PATH.")

if __name__ == "__main__":
    DOT_FILENAME = "x.dot"
    if len(sys.argv) > 1:
        DOT_FILENAME = sys.argv[1]

    if not os.path.exists(DOT_FILENAME):
        print(f"File {DOT_FILENAME} not found.")
    else:
        generate_latex_and_makefile(DOT_FILENAME)
