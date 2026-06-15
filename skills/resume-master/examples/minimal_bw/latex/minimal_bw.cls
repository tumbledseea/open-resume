%%
%% template4.cls — minimal black-and-white academic/classic resume
%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{minimal_bw}[2026/06/13 Template4 resume class]

\LoadClass[10pt,a4paper]{article}

\RequirePackage[top=1.6cm,bottom=1.4cm,left=1.8cm,right=1.8cm]{geometry}
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
\RequirePackage{enumitem}
\RequirePackage[hidelinks]{hyperref}
\RequirePackage{ifthen}
\RequirePackage{etoolbox}

\definecolor{t4text}{HTML}{111111}
\definecolor{t4muted}{HTML}{555555}
\definecolor{t4rule}{HTML}{AAAAAA}

\pagecolor{white}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}

\setlist[itemize]{
  leftmargin=1.1em, itemsep=0.06em, topsep=0.08em,
  parsep=0pt, partopsep=0pt, label={--}
}

%% Header: name centre, contact line below
\newcommand{\Header}[2]{%
  \begin{center}
    {\fontsize{24}{28}\selectfont\bfseries\color{t4text}#1}\par
    \vspace{0.3em}
    {\small\color{t4muted}#2}\par
    \vspace{0.4em}
  \end{center}
  \noindent\textcolor{t4rule}{\rule{\textwidth}{0.8pt}}\par
  \vspace{0.25em}
}

%% Section title: all-caps, underlined
\newcommand{\SectionTitle}[1]{%
  \vspace{0.3em}
  \noindent{\normalsize\bfseries\color{t4text}\MakeUppercase{#1}}\par
  \noindent\textcolor{t4rule}{\rule{\textwidth}{0.4pt}}\par
  \vspace{0.08em}
}

\newcommand{\EntryHeader}[2]{%
  \noindent\textbf{\color{t4text}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t4muted}#2}}%
  \par
}
\newcommand{\EntrySubheader}[2]{%
  \noindent{\small\itshape\color{t4muted}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t4muted}#2}}%
  \par
}
\newcommand{\AwardEntry}[2]{%
  \noindent{\color{t4text}#1}%
  \ifthenelse{\equal{#2}{}}{}{\hfill{\small\color{t4muted}#2}}%
  \par\vspace{0.06em}
}
