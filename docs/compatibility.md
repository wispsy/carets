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
Windows console input path is not qualified. Grapheme segmentation uses bundled
Unicode 18 data and passes its official conformance fixture. Cell width follows
the documented policy and does not promise font-dependent shaping. Constraint
layout, incremental input protocols, frame coalescing and component/theme/shell
contracts ship in 0.2.0. The full widget backlog remains in issue #7. The optional
Headless Spreadsheets snapshot integration is separately qualified on Python
3.14 on Linux/macOS/Windows. No global input listener is installed.
