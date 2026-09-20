# GenStat Scriptable Widget

A lightweight iPhone Home Screen widget showing current generator status, built for the [Scriptable](https://apps.apple.com/us/app/scriptable/id1405459188) app (free, no account required).

It exists as an alternative to the native iOS app in [`GenStat/`](../GenStat): if that app isn't published to the App Store, a free-tier ("personal team") code signature expires after 7 days and has to be reinstalled via cable. This widget has no signing, no expiry, and no build step — it's just a script running inside Scriptable.

---

## What it does

`GenStat.js` fetches the single row from the `generator_status` table directly via the Supabase REST API and renders it as a colored Home Screen tile:

- **Green** — Normal (utility power, generator idle)
- **Blue** — Weekly Test (generator exercising)
- **Orange** — Outage (generator supplying the house)
- **Red** — Critical (utility down, generator not running)
- **Gray** — Unknown, or the fetch failed

It shows the state, utility/generator voltage, and how long ago the data was last updated.

---

## Setup

1. Install **Scriptable** from the App Store on your iPhone (free).
2. Open Scriptable, tap **"+"** to create a new script.
3. Copy the contents of [`GenStat.js`](GenStat.js) and paste it in.
4. Rename the script to **"GenStat"** (tap the name at the top).
5. Tap the ▶️ run button once to confirm it renders correctly with your current status.
6. Long-press your iPhone Home Screen → tap **"+"** in the top corner → search **"Scriptable"** → choose the **small** widget size → tap **"Add Widget."**
7. Long-press the new widget → **"Edit Widget"** → set **Script** to **"GenStat."**

From then on it refreshes automatically — iOS controls the exact timing (typically every 15–30 minutes), not the script.

---

## Configuration

The Supabase URL and key are hardcoded near the top of `GenStat.js`:

```js
const SUPABASE_URL = "https://your-project.supabase.co"
const SUPABASE_KEY = "sb_publishable_..."
```

These match the values in the project root's `Secrets.xcconfig`. The key used here is the **publishable/anon key** — safe to embed in client-side code like this widget, the same one the iOS app ships with. Never put the Supabase service-role key here.

If your `generator_status` table or column names differ from the schema in [`supabase/schema.sql`](../supabase/schema.sql), update the `select=` query string in `fetchStatus()` accordingly.

---

## Limitations

- **Not real-time.** iOS budgets widget refreshes on its own schedule; this is a glance-at-it tile, not a live feed. Time-sensitive alerts (outage, critical) still come through the app's APNs push notifications, not this widget.
- **Read-only.** The widget only displays status — it can't acknowledge alerts, exercise the generator, or do anything the iOS app can.
- **One generator.** Like the rest of GenStat, this assumes a single `generator_status` row (`id = 1`).
