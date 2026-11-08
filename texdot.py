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
import psutil

def is_zathura_running() -> bool:
    """Check if zathura is running using psutil."""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] == 'zathura':
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

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

    extracted_items = []
    updated_count = 0

    # Process all nodes
    for node in graph.get_nodes():
        comment_attr = unquote(node.get('comment'))
        image_attr = unquote(node.get('image'))
        label_raw = node.get('label')

        if comment_attr:
            if image_attr:
                print(f"Error: Node '{node.get_name()}' contains both an 'image' attribute and a 'comment' attribute. The image attribute is now automatically generated.")
                sys.exit(1)
            if label_raw is not None:
                print(f"Error: Node '{node.get_name()}' contains both a 'label' attribute and a 'comment' attribute. No label is allowed if a comment attribute is present.")
                sys.exit(1)

            base_name = unquote(node.get_name())
            tex_filename = f"{base_name}.tex"
            png_filename = f"{base_name}.png"

            if not is_valid_linux_filename(tex_filename) or not is_valid_linux_filename(png_filename):
                print(f"Error: Node ID '{base_name}' produces invalid Linux filenames. Filenames cannot contain '/' or exceed 255 bytes.")
                sys.exit(1)

            tex_content = template.replace(r'\end{document}', f"{comment_attr}\n\\end{{document}}")

            if write_if_changed(tex_filename, tex_content):
                updated_count += 1

            extracted_items.append({'base': base_name, 'png': png_filename, 'tex': tex_filename})

            # Inject auto-generated image and searchable label attributes
            node.set('image', f'"{png_filename}"')
            node.set_label(make_searchable_dot_label(tex_content))
            node.set('fontname', '"Courier"')
            node.set('fontsize', '"5"')
            node.set('fontcolor', '"#00000001"')

    # Process all edges and inject the HTML label
    for edge in graph.get_edges():
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

        # Check if zathura is already running
        zathura_running = False
        try:
            res = subprocess.run(["pgrep", "-x", "zathura"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            zathura_running = (res.returncode == 0)
        except FileNotFoundError:
            pass

        if not zathura_running:
            print(f"Opening {target_pdf} in zathura...")
            subprocess.Popen(["zathura", target_pdf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print(f"{target_pdf} updated (zathura will auto-reload).")

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
