%%
%% template6.cls — dark left sidebar + light right content
%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{dark_sidebar}[2026/06/13 Template6 resume class]

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

\definecolor{t6dark}{HTML}{2C2C2C}
\definecolor{t6accent}{HTML}{E8B84B}
\definecolor{t6light}{HTML}{F5F5F0}
\definecolor{t6text}{HTML}{1A1A1A}
\definecolor{t6muted}{HTML}{888888}
\definecolor{t6rule}{HTML}{DDDDDD}
\definecolor{t6white}{HTML}{FFFFFF}

\pagecolor{t6light}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}

\setlist[itemize]{
  leftmargin=1.1em, itemsep=0.07em, topsep=0.1em,
  parsep=0pt, partopsep=0pt,
  label={\textcolor{t6accent}{\small$\bullet$}}
}

%% Sidebar header: name + contact in dark panel
\newcommand{\SideHeader}[3]{%
  \begin{center}\vspace{3mm}
    \ifblank{#3}{%
      \begin{tikzpicture}
        \draw[t6accent,fill=t6dark] (0,0) circle (1.1cm);
        \draw[t6muted] (0,0.25cm) circle (0.35cm);
        \draw[t6muted,rounded corners=5pt] (-0.5cm,-0.65cm) rectangle (0.5cm,-0.05cm);
      \end{tikzpicture}
    }{\includegraphics[width=2.2cm,height=2.2cm,keepaspectratio]{#3}}%
    \[2mm]
    {\fontsize{15}{18}\selectfont\bfseries\color{t6white}#1}\[1mm]
    {\small\color{t6accent}#2}\[2mm]
  \end{center}
}

\newcommand{\SideSection}[1]{%
  \vspace{1.5mm}
  {\small\bfseries\color{t6accent}\MakeUppercase{#1}}\[-1mm]
  \textcolor{t6accent}{\rule{\linewidth}{0.4pt}}\[0.5mm]
}

\newcommand{\ContactItem}[2]{%
  {\small\color{t6muted}#1}\enspace{\small\color{t6white}#2}\[0.5mm]
}

\newtcolorbox{T6SideBox}{
  enhanced, colback=t6dark, colframe=t6dark,
  boxrule=0pt, arc=0pt,
  left=4mm, right=4mm, top=0pt, bottom=0pt,
  height=\textheight, valign=top
}

\newtcolorbox{T6Card}{
  enhanced, colback=t6white, colframe=t6rule,
  boxrule=0.3pt, arc=2mm,
  left=3mm, right=3mm, top=1.5mm, bottom=1.5mm,
  before skip=0.1em, after skip=0.25em
}

\newcommand{\SectionTitle}[1]{%
  \vspace{0.18em}
  \noindent{\color{t6accent}\rule{4pt}{11pt}}\hspace{0.4em}%
  {\large\bfseries\color{t6text}#1}\hspace{0.5em}%
  \textcolor{t6rule}{\rule{0.60\linewidth}{0.4pt}}\par
  \vspace{0.1em}
}

\newcommand{\EntryHeader}[2]{%
  \noindent\textbf{\color{t6text}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t6accent}#2}}\par
}
\newcommand{\EntrySubheader}[2]{%
  \noindent{\small\color{t6muted}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t6muted}#2}}\par
}
\newcommand{\AwardEntry}[2]{%
  \noindent{\color{t6text}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t6muted}#2}}\par\vspace{0.07em}
}
