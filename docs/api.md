# Public API reference

| API | Contract |
| --- | --- |
| Program.run/dispatch/post/stop | Serial model messages; explicit application lifetime |
| Program.schedule/cancel/add_cleanup/idle | Owned command IDs, cleanup and current-delivery draining |
| Command/CommandErrorMsg | Sync/async producers, delays/ticks and explicit background failures |
| TerminalSession/Options/Capabilities | Scoped modes/signals, resize and conservative fallbacks |
| KeyMsg/MouseMsg/WindowSizeMsg/BatchMsg | Typed application input and flattened batches |
| AnsiInputParser.feed/finish | Incremental UTF-8/common ANSI protocol decoding |
| CellDiffRenderer/ScreenBuffer | Screen cells and diff rendering |
| Style/Border/visual_width/truncate_ansi | Styled display text and width helpers |
| ZoneManager/ZoneInfo | Caller-owned component rectangles and hit testing |
| FocusManager/FocusComponent/FocusEvent | Scoped navigation and capture/target/bubble routing |
| Form/Group/TypedField/FormResult | Typed data, validation timing and explicit outcome states |
| InputField/SelectField/ConfirmField | Existing declarative field schemas |
| ApplicationContext/load_config | Explicit services/config and external diagnostics |
| carets.components | TextInput, ListModel, Spinner and Viewport update/view models |
| carets.testing | FakeTerminal, ManualClock, SnapshotRenderer, TestProgram and assert_layout |

See the linked lifecycle, terminal, focus, forms/services, testing and tutorial
guides for examples and behavioral limits. The toolkit does not parse or execute
workflow documents; application libraries supply that behavior.
