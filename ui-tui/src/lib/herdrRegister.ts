import net from 'node:net'

type JsonRpcResponse = {
  error?: { code?: string; message?: string }
  id?: string
  result?: unknown
}

type PaneInfoResult = {
  pane?: {
    workspace_id?: string
  }
  type?: string
}

type WorkspaceInfoResult = {
  type?: string
  workspace?: {
    pane_count?: number
    workspace_id?: string
  }
}

const truthy = (value: string | undefined) => /^(?:1|true|yes|on)$/i.test((value ?? '').trim())

const rpc = (socketPath: string, method: string, params: Record<string, unknown>): Promise<JsonRpcResponse> =>
  new Promise(resolve => {
    const id = `hermes-tui-herdr:${method}:${Date.now()}:${Math.floor(Math.random() * 1_000_000)}`
    const client = net.createConnection(socketPath)
    let settled = false
    let buf = ''

    const finish = (response: JsonRpcResponse) => {
      if (settled) {
        return
      }
      settled = true
      client.destroy()
      resolve(response)
    }

    client.setTimeout(400)
    client.on('connect', () => {
      client.write(`${JSON.stringify({ id, method, params })}\n`)
    })
    client.on('data', chunk => {
      buf += chunk.toString('utf8')
      const line = buf.split('\n')[0]
      if (!line) {
        return
      }
      try {
        finish(JSON.parse(line) as JsonRpcResponse)
      } catch (err) {
        finish({ error: { message: err instanceof Error ? err.message : String(err) } })
      }
    })
    client.on('timeout', () => finish({ error: { message: 'timeout' } }))
    client.on('error', err => finish({ error: { message: err.message } }))
    client.on('end', () => {
      if (!settled) {
        finish({ error: { message: 'socket ended before response' } })
      }
    })
  })

const paneInfo = (response: JsonRpcResponse): PaneInfoResult | undefined => {
  if (!response.result || typeof response.result !== 'object') {
    return undefined
  }

  return response.result as PaneInfoResult
}

const workspaceInfo = (response: JsonRpcResponse): WorkspaceInfoResult | undefined => {
  if (!response.result || typeof response.result !== 'object') {
    return undefined
  }

  return response.result as WorkspaceInfoResult
}

/**
 * Make Atlas TUI panes self-identify to Herdr's outer chrome.
 *
 * Herdr exposes HERDR_PANE_ID inside the PTY (for example `p_45`) while the
 * public CLI often lists workspace-shaped ids (for example `w...-1`). Herdr's
 * socket maps the env id correctly. Reporting agent status alone is not enough:
 * the left `spaces` nav is driven by workspace/pane labels, so Atlas mode must
 * explicitly rename both layers at startup.
 */
export async function registerHerdrAtlasPaneFromEnv(env: NodeJS.ProcessEnv = process.env): Promise<void> {
  if (!truthy(env.HERMES_TUI_ATLAS_PANE) || env.HERDR_ENV !== '1') {
    return
  }

  const socketPath = env.HERDR_SOCKET_PATH
  const paneId = env.HERDR_PANE_ID
  const paneName = (env.HERMES_TUI_PANE_NAME || '').trim()

  if (!socketPath || !paneId || !paneName) {
    return
  }

  try {
    const renamed = await rpc(socketPath, 'pane.rename', { pane_id: paneId, label: paneName })
    const workspaceId = paneInfo(renamed)?.pane?.workspace_id

    if (workspaceId) {
      const workspace = workspaceInfo(await rpc(socketPath, 'workspace.get', { workspace_id: workspaceId }))?.workspace

      // Herdr's left `spaces` nav is workspace-level. Rename it for normal
      // one-pane Atlas spaces, but do not let an advanced internal split
      // overwrite the parent workspace name.
      if ((workspace?.pane_count ?? 1) <= 1) {
        await rpc(socketPath, 'workspace.rename', { workspace_id: workspaceId, label: paneName })
      }
    }

    await rpc(socketPath, 'pane.report_agent', {
      agent: 'Atlas',
      label: paneName,
      message: 'awaiting input',
      pane_id: paneId,
      seq: Date.now() * 1_000 + Math.floor(Math.random() * 1_000),
      source: `custom:atlas:${paneName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'pane'}`,
      state: 'idle'
    })
  } catch {
    // Best-effort only: Herdr chrome metadata must never block the TUI from opening.
  }
}
