# graphviz_latex_pipeline

New ```texdot.py``` tool is result of less than 1h chat with Gemini Pro. It enables LaTeX labels for Graphviz nodes and edges. The LaTeX is stored in node or edge ```comment``` attribute. The ```image``` attribute specifies the filename the compiled LaTeX will be stored into. The adustable template is stored in graph ```comment``` attribute. Executing ```./texdot.py demo.dot``` will
- parse demo.dot using ```pydot``` interface
- create temporary .tex file for each LaTeX label
- create ```Makefile``` to orchestrate the work
- use ```latexmk``` to compile into .pdf file
- use ```pdftocairo``` to create needed image
- execute ```dot``` to create final .pdf
- execute ```evince``` to display the result

When run first a lot of output will appear. When run again without changes in the LaTeX labels, incremental compilation avoids regeneration of the images:  
```
hermann@8840hs:~/graphviz_latex_pipeline$ ./texdot.py demo.dot 
Extracted 3 LaTeX definitions (0 newly written/updated).
Running make...
dot -Tpdf demo_processed.dot -o demo.pdf
Successfully generated demo.pdf.
Opening demo.pdf in evince...
hermann@8840hs:~/graphviz_latex_pipeline$ 
```

To get rid of the many temporary files just execute ```make clean```, it deletes the Makefile as well.

LaTeX labels are really easy:  
(edges do not have ```image``` attribute normally, ```texdot.py``` creates HTML workaround)  
```
...
    lem_1_5 [label="" shape=box image="lem_1_5.png" comment="
\textbf{Lem 1.5 }For distinct $a,b,c\in \mathbb{Q}$ define $B, \tilde{C}$ and C\\
$B=\{(u,v,w)\in \mathbb{Q}\times\mathbb{Q}\times\mathbb{Q}\vert u^2+a=v^2+b=w^2+c\}$\\
"]
    lem_1_6 [label="" shape=box image="lem_1_6.png" comment="
\textbf{Lem 1.6 } ...\\
"]

    lem_1_5 -> lem_1_6 [label="" image="1_5.1_6.png" comment="
\textbf{wow } $\exists\ \dots$
"]

}
```

And this is 50% size PDF view of created result:  
![demo.pdf.png](res/demo.pdf.png)


## work in progress

Transforming [number_theory.dot](number_theory.dot) from old system to new, 4 node labels (of 37) on right side are processed with ```texdot.py```. Since there are no ```comment``` and ```image``` attributes in the not yet transformed 33 node labels, ```texdot.py``` can process the whole document, all the time. 3 node labels using the old system can be seen on left side. The HTML label content in number_theory.dot node and edge labels was created with the [old tool](https://gist.github.com/Hermann-SW/12c7644ac0c75b4eb019f76c3f023fe5).

Below is the adaptable LaTeX template in graph ```comment``` attribute. I had to add package for ```\psi```, and shortcut for $\mathbb{Z}$ is available now. I commented out the math spacing removal for now:  
```dot
    comment="
\documentclass[varwidth=true, border=5pt]{standalone}
\usepackage{amsmath, amsfonts, amsthm, amssymb}

\newcommand\Z{\ensuremath{\mathbb{Z}}}

\begin{document}
% Remove automatic math spacing
%\thinmuskip=0mu
%\medmuskip=0mu
%\thickmuskip=0mu

\end{document}
"
```

I use ```vi``` editor since 1990, and write+compile is just done with ```:w|!T```, with:
```bash
$ cat /usr/local/bin/T
#!/bin/bash
./texdot.py number_theory.dot
$
```

![work_in_progress.png](res/work_in_progress.png)
