# Compatibility and capability fallbacks

| Surface | Qualification |
| --- | --- |
| Library floor | Python 3.10; Linux source and installed wheel/source tests |
| Other supported interpreters | Linux source checks on 3.11, 3.12 and 3.13 |
| Current installed profiles | Python 3.14 on Linux, macOS and Windows |
| Terminal lifecycle/focus/forms | Synthetic fixtures on every selected installed platform |
| POSIX raw restoration | Real pseudo-terminal test on Linux/macOS |
| Native POSIX buffered stdin | Independent-process pseudo-terminal single-key delivery regression |
| Native Windows raw/ANSI console | Conservative fallback; no native-console support claim |
| Redirected streams / TERM=dumb | No unsupported terminal control output |

SIGWINCH is used only where available; process signal handlers require the main
thread. Input add_reader support depends on the event loop/platform. Windows apps
can supply synthetic or application-owned message sources; the default native
Windows console input path is not qualified. Unicode cell-width calculation is
an approximation and does not promise full emoji/grapheme shaping. Optional
constraint layout, advanced protocol coverage and richer widgets retain their
own roadmap issues. No global input listener is installed.
