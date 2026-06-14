%%
%% template1.cls - card-style Chinese resume template
%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{red_card}[2026/06/09 Template1 resume class]

\LoadClass[10pt,a4paper]{article}

\RequirePackage[top=0.95cm,bottom=0.95cm,left=1.25cm,right=1.25cm]{geometry}
\RequirePackage{ctex}
\RequirePackage{xcolor}
\RequirePackage{graphicx}
\RequirePackage{tikz}
\RequirePackage{eso-pic}
\RequirePackage[most]{tcolorbox}
\RequirePackage{enumitem}
\RequirePackage[hidelinks]{hyperref}
\RequirePackage{ifthen}
\RequirePackage{etoolbox}

\definecolor{templatebg}{HTML}{F2F6FA}
\definecolor{templateaccent}{HTML}{C7443E}
\definecolor{templatedark}{HTML}{22272E}
\definecolor{templatemuted}{HTML}{6B7280}
\definecolor{templateborder}{HTML}{DCE5EF}
\definecolor{templaterule}{HTML}{CDD6E1}

\pagecolor{templatebg}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}
\setlength{\emergencystretch}{2em}

\setlist[itemize]{
  leftmargin=1.15em,
  itemsep=0.08em,
  topsep=0.12em,
  parsep=0pt,
  partopsep=0pt
}

\AddToShipoutPictureBG*{%
  \begin{tikzpicture}[remember picture,overlay]
    \fill[templateaccent] (current page.north west)
      rectangle ([yshift=-0.28cm]current page.north east);
  \end{tikzpicture}%
}

\newtcolorbox{TemplateCard}{
  enhanced,
  colback=white,
  colframe=templateborder,
  boxrule=0.35pt,
  arc=2.2mm,
  left=3mm,
  right=3mm,
  top=1.7mm,
  bottom=1.7mm,
  before skip=0.12em,
  after skip=0.28em
}

\newcommand{\PhotoPlaceholder}{%
  \begin{tikzpicture}
    \draw[templateborder,fill=white,rounded corners=2pt] (0,0) rectangle (2.15,2.55);
    \draw[templaterule] (0.35,1.05) circle (0.28);
    \draw[templaterule,rounded corners=6pt] (0.58,0.35) rectangle (1.57,0.9);
  \end{tikzpicture}%
}

\newcommand{\TemplateHeader}[3]{%
  \vspace*{0.22cm}
  \noindent
  \begin{minipage}[t]{0.78\textwidth}
    {\fontsize{20}{23}\selectfont\bfseries\color{templatedark}#1}\par
    \vspace{0.28em}
    {\small\color{templatemuted}#2}\par
  \end{minipage}%
  \hfill
  \begin{minipage}[t]{0.16\textwidth}
    \raggedleft
    \ifblank{#3}{%
      \PhotoPlaceholder
    }{%
      \includegraphics[width=2.15cm,height=2.55cm,keepaspectratio]{#3}
    }%
  \end{minipage}\par
  \vspace{0.26em}
}

\newcommand{\TemplateSectionTitle}[1]{%
  \vspace{0.18em}
  \noindent
  \begin{minipage}{\textwidth}
    \begin{tikzpicture}[baseline=-0.58ex]
      \fill[templateaccent] (0,0) circle (0.12cm);
      \fill[white] (0,0) circle (0.045cm);
    \end{tikzpicture}%
    \hspace{0.35em}{\large\bfseries\color{templateaccent}#1}%
    \hspace{0.65em}\textcolor{templaterule}{\rule{0.66\textwidth}{0.45pt}}%
  \end{minipage}\par
  \vspace{0.12em}
}

\newcommand{\Badge}[1]{%
  \hspace{0.3em}{\tikz[baseline=-0.5ex]\node[
    fill=templatebg,
    draw=templateborder,
    rounded corners=1.4pt,
    inner xsep=3.2pt,
    inner ysep=1.0pt,
    font=\scriptsize\bfseries\color{templateaccent}
  ]{#1};}%
}

\newcommand{\EntryHeader}[2]{%
  \noindent\textbf{\color{templatedark}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{templatemuted}#2}}%
  \par
}

\newcommand{\EntrySubheader}[2]{%
  \noindent{\small\color{templatemuted}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{templatemuted}#2}}%
  \par
}

\newcommand{\AwardEntry}[2]{%
  \noindent #1%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{templatemuted}#2}}%
  \par\vspace{0.08em}
}
