%%
%% template8.cls — deep purple modern resume
%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{purple_tech}[2026/06/13 Template8 resume class]

\LoadClass[10pt,a4paper]{article}

\RequirePackage[top=0cm,bottom=0.9cm,left=1.3cm,right=1.3cm]{geometry}
\RequirePackage[fontset=none]{ctex}
% Bind bundled Adobe CJK fonts (relative to compile cwd = <project>/latex).
% Convention: body = Song, bold = Hei, italic = Kai.
\def\CJKfontdir{../../fonts/zh_CN-Adobe/}
\setCJKmainfont{AdobeSongStd-Light.otf}[
  Path=\CJKfontdir,
  BoldFont=AdobeHeitiStd-Regular.otf,
  ItalicFont=AdobeKaitiStd-Regular.otf
]
\setCJKsansfont{AdobeHeitiStd-Regular.otf}[Path=\CJKfontdir]
\setCJKmonofont{AdobeKaitiStd-Regular.otf}[Path=\CJKfontdir]
\newCJKfontfamily\songti{AdobeSongStd-Light.otf}[Path=\CJKfontdir]
\newCJKfontfamily\heiti{AdobeHeitiStd-Regular.otf}[Path=\CJKfontdir]
\newCJKfontfamily\kaiti{AdobeKaitiStd-Regular.otf}[Path=\CJKfontdir]
\RequirePackage{xcolor}
\RequirePackage{graphicx}
\RequirePackage{tikz}
\RequirePackage{eso-pic}
\RequirePackage[most]{tcolorbox}
\RequirePackage{enumitem}
\RequirePackage[hidelinks]{hyperref}
\RequirePackage{ifthen}
\RequirePackage{etoolbox}

\definecolor{t8topbar}{HTML}{4A2580}
\definecolor{t8accent}{HTML}{7B42CC}
\definecolor{t8mid}{HTML}{9D68D8}
\definecolor{t8bg}{HTML}{F8F5FF}
\definecolor{t8text}{HTML}{1A1030}
\definecolor{t8muted}{HTML}{6B5880}
\definecolor{t8rule}{HTML}{D5C5EE}
\definecolor{t8badge}{HTML}{EDE0FF}

\pagecolor{t8bg}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}
\setlength{\emergencystretch}{2em}

\setlist[itemize]{
  leftmargin=1.1em, itemsep=0.07em, topsep=0.1em,
  parsep=0pt, partopsep=0pt,
  label={\textcolor{t8accent}{\small$\bullet$}}
}

\AddToShipoutPictureBG*{%
  \begin{tikzpicture}[remember picture,overlay]
    \fill[t8topbar] (current page.north west)
      rectangle ([yshift=-0.35cm]current page.north east);
  \end{tikzpicture}%
}

\newcommand{\Header}[3]{%
  \vspace*{0.45cm}
  \noindent
  \begin{minipage}[t]{0.76\textwidth}
    {\fontsize{22}{26}\selectfont\bfseries\color{t8text}#1}\par
    \vspace{0.22em}{\small\color{t8muted}#2}
  \end{minipage}%
  \hfill
  \begin{minipage}[t]{0.18\textwidth}
    \raggedleft
    \ifblank{#3}{%
      \begin{tikzpicture}
        \draw[t8rule,fill=white,rounded corners=2pt] (0,0) rectangle (2.1,2.5);
        \draw[t8rule] (0.6,1.55) circle (0.35cm);
        \draw[t8rule,rounded corners=5pt] (0.3,0.35) rectangle (1.8,1.1);
      \end{tikzpicture}%
    }{\includegraphics[width=2.1cm,height=2.5cm,keepaspectratio]{#3}}%
  \end{minipage}\par
  \vspace{0.28em}
  \noindent\textcolor{t8accent}{\rule{\textwidth}{1.2pt}}\par
  \vspace{0.12em}
}

\newcommand{\SectionTitle}[1]{%
  \vspace{0.22em}
  \noindent
  \begin{tikzpicture}[baseline=-0.55ex]
    \fill[t8accent] (0,-0.12) rectangle (0.22,0.82);
  \end{tikzpicture}%
  \hspace{0.45em}{\large\bfseries\color{t8accent}#1}%
  \hspace{0.6em}\textcolor{t8rule}{\rule{0.62\textwidth}{0.4pt}}%
  \par\vspace{0.1em}
}

\newtcolorbox{T8Card}{
  enhanced, colback=white, colframe=t8rule,
  boxrule=0.4pt, arc=2mm,
  left=3.5mm, right=3.5mm, top=1.8mm, bottom=1.8mm,
  before skip=0.1em, after skip=0.28em
}

\newcommand{\Badge}[1]{%
  \hspace{0.25em}{\tikz[baseline=-0.45ex]\node[
    fill=t8badge, draw=t8rule, rounded corners=1.5pt,
    inner xsep=3pt, inner ysep=0.8pt,
    font=\scriptsize\bfseries\color{t8accent}
  ]{#1};}%
}

\newcommand{\EntryHeader}[2]{%
  \noindent\textbf{\color{t8text}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t8accent}#2}}\par
}
\newcommand{\EntrySubheader}[2]{%
  \noindent{\small\color{t8muted}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t8muted}#2}}\par
}
\newcommand{\AwardEntry}[2]{%
  \noindent{\color{t8text}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t8muted}#2}}%
  \par\vspace{0.07em}
}
