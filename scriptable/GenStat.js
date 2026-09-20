// GenStat — Home Screen widget showing generator status via Supabase

const SUPABASE_URL = "https://lptqugsuefnccrwtbejw.supabase.co"
const SUPABASE_KEY = "sb_publishable_O9h8A65qbSEbZ0zWxmMPIg_8zjUvVrm"

const STATE_INFO = {
  normal:      { label: "Normal",      color: new Color("#2ecc71"), emoji: "✅" },
  weekly_test: { label: "Weekly Test", color: new Color("#3498db"), emoji: "🔄" },
  outage:      { label: "OUTAGE",      color: new Color("#e67e22"), emoji: "⚡" },
  critical:    { label: "CRITICAL",    color: new Color("#e74c3c"), emoji: "🚨" },
  unknown:     { label: "Unknown",     color: new Color("#7f8c8d"), emoji: "❔" },
}

async function fetchStatus() {
  const url = `${SUPABASE_URL}/rest/v1/generator_status?id=eq.1&select=current_state,utility_voltage,generator_voltage,updated_at`
  const req = new Request(url)
  req.headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": `Bearer ${SUPABASE_KEY}`,
  }
  const rows = await req.loadJSON()
  return rows && rows.length > 0 ? rows[0] : null
}

function minutesAgo(isoString) {
  if (!isoString) return "unknown"
  const diffMs = Date.now() - new Date(isoString).getTime()
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return "just now"
  if (mins === 1) return "1 min ago"
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  return `${hrs}h ago`
}

async function buildWidget() {
  const widget = new ListWidget()
  widget.setPadding(14, 14, 14, 14)

  let data
  try {
    data = await fetchStatus()
  } catch (e) {
    data = null
  }

  if (!data) {
    widget.backgroundColor = new Color("#7f8c8d")
    const title = widget.addText("GenStat")
    title.font = Font.boldSystemFont(14)
    title.textColor = Color.white()
    widget.addSpacer(6)
    const err = widget.addText("⚠️ Could not load status")
    err.font = Font.systemFont(13)
    err.textColor = Color.white()
    return widget
  }

  const info = STATE_INFO[data.current_state] || STATE_INFO.unknown
  widget.backgroundColor = info.color

  const title = widget.addText("GenStat")
  title.font = Font.boldSystemFont(13)
  title.textColor = Color.white()
  title.textOpacity = 0.85

  widget.addSpacer(6)

  const status = widget.addText(`${info.emoji} ${info.label}`)
  status.font = Font.boldSystemFont(20)
  status.textColor = Color.white()

  widget.addSpacer(8)

  const utility = widget.addText(`Utility: ${data.utility_voltage ?? "—"}V`)
  utility.font = Font.systemFont(12)
  utility.textColor = Color.white()

  const generator = widget.addText(`Generator: ${data.generator_voltage ?? "—"}V`)
  generator.font = Font.systemFont(12)
  generator.textColor = Color.white()

  widget.addSpacer(6)

  const updated = widget.addText(`Updated ${minutesAgo(data.updated_at)}`)
  updated.font = Font.systemFont(10)
  updated.textColor = Color.white()
  updated.textOpacity = 0.75

  widget.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000)

  return widget
}

const widget = await buildWidget()
if (config.runsInWidget) {
  Script.setWidget(widget)
} else {
  widget.presentSmall()
}
Script.complete()
