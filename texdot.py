#!/usr/bin/env python3
""" make pylint happy """
# pylint: disable=line-too-long,too-many-locals,consider-using-with
import os
import sys
import subprocess
import pydot

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

    extracted_items = []
    updated_count = 0

    # Process all nodes
    for node in graph.get_nodes():
        image_attr = unquote(node.get('image'))
        comment_attr = unquote(node.get('comment'))

        if image_attr and comment_attr:
            base_name = image_attr[:-4] if image_attr.endswith('.png') else image_attr
            tex_filename = f"{base_name}.tex"
            tex_content = template.replace(r'\end{document}', f"{comment_attr}\n\\end{{document}}")

            if write_if_changed(tex_filename, tex_content):
                updated_count += 1

            extracted_items.append({'base': base_name, 'png': image_attr, 'tex': tex_filename})

    # Process all edges and inject the HTML label
    for edge in graph.get_edges():
        image_attr = unquote(edge.get('image'))
        comment_attr = unquote(edge.get('comment'))
        label_attr = unquote(edge.get('label'))

        # Error out if both label and comment are present (ignoring empty string labels)
        if comment_attr and label_attr:
            print(f"Error: Edge from {edge.get_source()} to {edge.get_destination()} contains both a 'label' (\"{label_attr}\") and a 'comment'. Aborting to prevent silent overwrite.")
            sys.exit(1)

        if image_attr and comment_attr:
            base_name = image_attr[:-4] if image_attr.endswith('.png') else image_attr
            tex_filename = f"{base_name}.tex"
            tex_content = template.replace(r'\end{document}', f"{comment_attr}\n\\end{{document}}")

            if write_if_changed(tex_filename, tex_content):
                updated_count += 1

            extracted_items.append({'base': base_name, 'png': image_attr, 'tex': tex_filename})

            # Auto-generate the HTML label for Graphviz
            html_label = f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR><TD><IMG SRC="{image_attr}"/></TD></TR></TABLE>>'
            edge.set_label(html_label)

    print(f"Extracted {len(extracted_items)} LaTeX definitions ({updated_count} newly written/updated).")

    # Save the processed Graphviz model to a temporary file
    processed_dot_file = dot_file.replace('.dot', '_processed.dot')
    graph.write(processed_dot_file)

    # Create the Makefile pointing to the temporary processed dot file
    target_pdf = dot_file.replace('.dot', '.pdf')
    all_pngs = " ".join([item['png'] for item in extracted_items])

    makefile_content = f"""# Auto-generated Makefile

all: {target_pdf}

# Final graph compilation depends on the processed .dot file and all generated .png labels
{target_pdf}: {processed_dot_file} {all_pngs}
\tdot -Tpdf {processed_dot_file} -o {target_pdf}

# Pattern rule: Convert .pdf to cropped .png using pdftocairo
%.png: %.pdf
\tpdftocairo -singlefile -png -transp -r 120 $< $*

# Pattern rule: Compile .tex to .pdf using latexmk
%.pdf: %.tex
\tlatexmk -pdf -lualatex $<

clean:
\t-latexmk -c
\trm -f *.tex *.pdf *.png {processed_dot_file} Makefile
"""

    write_if_changed('Makefile', makefile_content)

    # --- Automated Execution ---
    print("Running make...")
    try:
        subprocess.run(["make"], check=True)
        print(f"Successfully generated {target_pdf}.")

        print(f"Opening {target_pdf} in evince...")
        subprocess.Popen(["evince",target_pdf], stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    except subprocess.CalledProcessError as e:
        print(f"Compilation failed during make execution: {e}")
    except FileNotFoundError:
        print("Error: Make or Evince is not installed or not in PATH.")

if __name__ == "__main__":
    DOT_FILENAME = "x.dot"
    if len(sys.argv) > 1:
        DOT_FILENAME = sys.argv[1]

    if not os.path.exists(DOT_FILENAME):
        print(f"File {DOT_FILENAME} not found.")
    else:
        generate_latex_and_makefile(DOT_FILENAME)
