const truthy = (v?: string) => /^(?:1|true|yes|on)$/i.test((v ?? '').trim())

export const STARTUP_RESUME_ID = (process.env.HERMES_TUI_RESUME ?? '').trim()
export const STARTUP_QUERY = (process.env.HERMES_TUI_QUERY ?? '').trim()
export const STARTUP_IMAGE = (process.env.HERMES_TUI_IMAGE ?? '').trim()
export const MOUSE_TRACKING = !truthy(process.env.HERMES_TUI_DISABLE_MOUSE)
export const NO_CONFIRM_DESTRUCTIVE = truthy(process.env.HERMES_TUI_NO_CONFIRM)

// Skip AlternateScreen — TUI renders into the primary buffer so the host
// terminal's native scrollback captures whatever scrolls off the top.
// Experiment gate: lets us measure native scroll vs our virtualization on
// the same pipeline.
export const INLINE_MODE = truthy(process.env.HERMES_TUI_INLINE)

// Live FPS counter overlay, fed by ink's onFrame (real render rate, not a
// synthetic timer).
export const SHOW_FPS = truthy(process.env.HERMES_TUI_FPS)

// Atlas pane mode is a focused, task-driven presentation for running Hermes
// inside a Herdr pane.  It intentionally does not add voice/files here — this
// is only the solid visual shell Dave asked for.
export const ATLAS_PANE_MODE = truthy(process.env.HERMES_TUI_ATLAS_PANE)
export const ATLAS_PANE_NAME = (process.env.HERMES_TUI_PANE_NAME ?? '').trim()
