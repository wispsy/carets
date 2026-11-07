# Focus and routed events

FocusManager owns component IDs and active scopes over a caller-owned ZoneManager.
Register parents before children in the same scope; immutable FocusComponent
records hold disabled/read_only state. set_state updates state and repairs disabled
focus. indicator(id) supplies a visible focus marker for a view.

Tab/shift-tab moves among enabled components in the active scope. navigate also
supports geometric left/right/up/down movement using zone centers. activate(scope,
modal=True) traps focus until dismiss restores the previous scope and focus.
Mouse hit testing uses the topmost registered zone in the active scope; disabled
regions do not receive events or pass clicks through. Read-only components can
receive focus for inspection but do not receive editing events.

route sends events through ancestor capture, target, then ancestor bubble handlers.
Handlers receive FocusEvent(message, target, current, phase); event.stop() or a
truthy handler result stops propagation. Default tab navigation is consumed before
routing. Application models call route from update; no second input loop is added.
