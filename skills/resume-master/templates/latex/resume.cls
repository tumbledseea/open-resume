%%
%% resume.cls — LaTeX document class for one-page AI-generated resumes
%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{resume}[2026/06/08 Resume class v1.1]

\LoadClass[10pt,a4paper]{article}

% ── Tight margins for one-page ──
\RequirePackage[top=1.0cm, bottom=1.0cm, left=1.6cm, right=1.6cm]{geometry}

% ── Chinese & font support ──
\RequirePackage{ctex}

% ── Color ──
\RequirePackage{xcolor}
\definecolor{headerclr}{HTML}{2c3e50}
\definecolor{graytext}{HTML}{7f8c8d}
\definecolor{rulesep}{HTML}{dcdde1}

% ── Graphics (photo) ──
\RequirePackage{graphicx}
\RequirePackage{adjustbox}
\newif\ifshowphoto\showphotofalse
\newcommand{\setphoto}[2][3cm]{%
  \showphototrue
  \def\photopath{#2}%
  \def\photosize{#1}%
}

% ── Section formatting (compact) ──
\RequirePackage{titlesec}
\titleformat{\section}
  {\large\bfseries\color{headerclr}}
  {}{0em}{}%
  [\vspace{-0.3em}\textcolor{rulesep}{\rule{\textwidth}{0.5pt}}]
\titlespacing{\section}{0pt}{0.6em}{0.2em}

% ── Lists (compact) ──
\RequirePackage{enumitem}
\setlist{nosep,left=0.8em,itemsep=0pt,parsep=0pt,topsep=0pt}

% ── Hyperlinks ──
\RequirePackage[hidelinks]{hyperref}

% ── Page style: no page numbers ──
\pagestyle{empty}
\RequirePackage{parskip}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}

% ── Name & contact block ──
\newcommand{\basicinfo}[2]{%
  \noindent
  \begin{minipage}{\textwidth}
    {\huge\bfseries\color{headerclr} #1}%
    \ifshowphoto\hfill%
      \adjincludegraphics[height=\photosize,valign=t]{\photopath}%
    \fi\par
    {\small\color{graytext} #2}\par
  \end{minipage}\par
  \vspace{0.4em}
}

% ── Entry block (projects / internships) ──
\newcommand{\entry}[5]{%
  \noindent
  \begin{minipage}[t]{\textwidth}
    \textbf{\color{headerclr}#1}%
    \ifx&#3&\else\hfill{\color{graytext}\small #3}\fi\par
    \ifx&#2&\else
      \textit{\small\color{graytext} #2}%
      \ifx&#4&\else\hfill{\color{graytext}\small #4}\fi\par
    \fi
  \end{minipage}\par
  \vspace{0.05em}
  \ifx&#5&\else
    \begin{itemize}
      #5
    \end{itemize}%
  \fi
  \vspace{0.15em}
}

% ── Skill line ──
\newcommand{\skillitem}[2]{%
  \noindent\textbf{#1}：#2\par\vspace{0.06em}%
}

% ── Award / single-line item ──
\newcommand{\awarditem}[1]{%
  \noindent\textbullet\ #1\par\vspace{0.06em}%
}

% ── Summary / paragraph ──
\newcommand{\summarypara}[1]{%
  \noindent#1\par\vspace{0.1em}%
}
