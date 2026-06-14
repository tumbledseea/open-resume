%%
%% template2.cls - dual-column navy sidebar resume template
%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{navy_sidebar}[2026/06/13 Template2 resume class]

\LoadClass[10pt,a4paper]{article}

\RequirePackage[top=0pt,bottom=0pt,left=0pt,right=0pt]{geometry}
\RequirePackage{ctex}
\RequirePackage{xcolor}
\RequirePackage{graphicx}
\RequirePackage{tikz}
\RequirePackage{paracol}
\RequirePackage[most]{tcolorbox}
\RequirePackage{enumitem}
\RequirePackage[hidelinks]{hyperref}
\RequirePackage{ifthen}
\RequirePackage{etoolbox}

%% ── Palette ─────────────────────────────────────────────────────────
\definecolor{t2sidebar}{HTML}{1B2A4A}   % dark navy sidebar
\definecolor{t2accent}{HTML}{3D7DBF}    % medium blue accent
\definecolor{t2light}{HTML}{FFFFFF}
\definecolor{t2muted}{HTML}{B0BECD}
\definecolor{t2body}{HTML}{F7F9FC}
\definecolor{t2text}{HTML}{1F2937}
\definecolor{t2rule}{HTML}{D1DCE8}

\pagecolor{t2body}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}

\setlist[itemize]{
  leftmargin=1.1em,
  itemsep=0.07em,
  topsep=0.1em,
  parsep=0pt,
  partopsep=0pt,
  label={\textcolor{t2accent}{\small\textbullet}}
}

%% ── Sidebar block ───────────────────────────────────────────────────
\newenvironment{SidebarBlock}{%
  \begin{tcolorbox}[
    enhanced, colback=t2sidebar, colframe=t2sidebar,
    boxrule=0pt, arc=0pt,
    left=4mm, right=4mm, top=2mm, bottom=2mm,
    before skip=0pt, after skip=0pt
  ]%
  \color{t2light}%
}{%
  \end{tcolorbox}%
}

%% ── Main content card ───────────────────────────────────────────────
\newtcolorbox{MainCard}{
  enhanced, colback=white, colframe=t2rule,
  boxrule=0.3pt, arc=2mm,
  left=3mm, right=3mm, top=1.5mm, bottom=1.5mm,
  before skip=0.1em, after skip=0.25em
}

%% ── Header (sidebar top) ────────────────────────────────────────────
\newcommand{\T2SideHeader}[3]{%
  \begin{center}
    \vspace{2mm}
    \ifblank{#3}{%
      \begin{tikzpicture}
        \draw[t2muted,fill=t2sidebar] (0,0) circle (1cm);
        \draw[t2muted] (0,0.22cm) circle (0.32cm);
        \draw[t2muted,rounded corners=6pt] (-0.45cm,-0.65cm) rectangle (0.45cm,-0.08cm);
      \end{tikzpicture}
    }{%
      \includegraphics[width=2cm,height=2cm,keepaspectratio]{#3}
    }\\[2mm]
    {\fontsize{16}{19}\selectfont\bfseries\color{t2light}#1}\\[1mm]
    {\small\color{t2muted}#2}\\[2mm]
  \end{center}
}

%% ── Sidebar section title ───────────────────────────────────────────
\newcommand{\T2SideSection}[1]{%
  \vspace{1.5mm}
  {\small\bfseries\color{t2accent}\MakeUppercase{#1}}\\[-1mm]
  \textcolor{t2accent}{\rule{\linewidth}{0.4pt}}\\[0.5mm]
}

%% ── Sidebar contact item ────────────────────────────────────────────
\newcommand{\T2ContactItem}[2]{%
  {\small\color{t2muted}#1}\enspace{\small\color{t2light}#2}\\[0.5mm]
}

%% ── Main section title ──────────────────────────────────────────────
\newcommand{\T2SectionTitle}[1]{%
  \vspace{0.15em}
  \noindent
  \begin{minipage}{\linewidth}
    \noindent{\color{t2accent}\rule{3pt}{11pt}}\hspace{0.4em}%
    {\large\bfseries\color{t2text}#1}\hspace{0.5em}%
    \textcolor{t2rule}{\rule{0.6\linewidth}{0.4pt}}
  \end{minipage}\par
  \vspace{0.1em}
}

%% ── Entry helpers ───────────────────────────────────────────────────
\newcommand{\T2EntryHeader}[2]{%
  \noindent\textbf{\color{t2text}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t2accent}#2}}%
  \par
}

\newcommand{\T2EntrySubheader}[2]{%
  \noindent{\small\color{t2accent}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t2muted}#2}}%
  \par
}
