# Push Notifications Implementation Notes

## Status: WIP — Blocked on HTTP/2

All iOS and Supabase infrastructure is in place. The remaining blocker is
that Supabase Edge Functions (Deno) only support HTTP/1.1, but APNs requires
HTTP/2. APNs accepts the connection and returns 200 but silently drops the
notification. The fix is to route through an intermediary service.

## What's Working

- iOS app requests notification permission and registers for remote notifications
- APNs device token is obtained from Apple and upserted to Supabase `device_tokens` table
- Database webhook fires the `push-notification` Edge Function on `generator_events` INSERT
- Edge Function evaluates state transitions, builds notification content, signs APNs JWT (ES256)
- APNs key and device token are valid — Apple's Push Notification Console delivers test notifications successfully

## Apple Developer Configuration

- **Team**: Cluebucket Consulting, LLC (`4MUC8K263B`)
- **Bundle ID**: `studio.offbyone.KohlerStat`
- **APNs Key ID**: `Y4GY3CS3CF` (Sandbox & Production, created under Cluebucket team)
- **APNs Key File**: `AuthKey_Y4GY3CS3CF.p8` (stored locally, gitignored)
- **Push Notifications**: Enabled for the App ID in the developer portal

## Supabase Configuration

- **Project**: `lptqugsuefnccrwtbejw`
- **Edge Function**: `push-notification` (deployed)
- **Database Webhook**: `generator_events` INSERT triggers `push-notification`

### Supabase Secrets

| Secret | Value / Notes |
|--------|--------------|
| `APNS_KEY_ID` | `Y4GY3CS3CF` |
| `APNS_TEAM_ID` | `4MUC8K263B` |
| `APNS_PRIVATE_KEY` | Contents of `AuthKey_Y4GY3CS3CF.p8` |
| `APNS_USE_SANDBOX` | `true` (set for development; remove for production) |

### Database: `device_tokens` Table

```sql
CREATE TABLE device_tokens (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token text NOT NULL UNIQUE,
    platform text NOT NULL DEFAULT 'ios',
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_device_tokens_active ON device_tokens (active) WHERE active = true;
ALTER TABLE device_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow anon insert" ON device_tokens FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "Allow anon update" ON device_tokens FOR UPDATE TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon select for upsert" ON device_tokens FOR SELECT TO anon USING (true);
CREATE POLICY "Service role can read" ON device_tokens FOR SELECT TO service_role USING (true);
```

There is also an `update_updated_at()` trigger on the table.

## Files Changed

| File | Description |
|------|-------------|
| `GenStat/GenStat.entitlements` | Push Notifications capability (`aps-environment: development`) |
| `GenStat/GenStatApp.swift` | Added `@UIApplicationDelegateAdaptor`, notification permission request, `registerForRemoteNotifications` on MainActor |
| `GenStat/Services/AppDelegate.swift` | New — handles APNs token registration callback, `UNUserNotificationCenterDelegate` for foreground display |
| `GenStat/Services/SupabaseService.swift` | Added `Authorization` header to GET/POST, added `post(path:body:)` method, added `registerDeviceToken(_:)` with upsert (`on_conflict=token`) |
| `GenStatTests/DeviceTokenRegistrationTests.swift` | New — unit tests for token registration |
| `supabase/functions/push-notification/index.ts` | New — Edge Function for sending push notifications |
| `GenStat.xcodeproj/project.pbxproj` | Bundle ID → `studio.offbyone.KohlerStat`, DEVELOPMENT_TEAM → `4MUC8K263B`, entitlements reference |
| `.gitignore` | Added `*.p8` and `supabase/.temp/` |

## The HTTP/2 Problem

APNs requires HTTP/2 for push delivery. Supabase Edge Functions run on Deno
which uses HTTP/1.1 for `fetch()`. APNs accepts the HTTP/1.1 request and
returns status 200, but silently discards the notification. This was confirmed
by:

1. Sending via the Edge Function → APNs returns 200, no notification arrives
2. Sending via Apple's Push Notification Console → notification arrives immediately
3. Same device token and bundle ID in both cases

## Next Steps

### Option 1: Firebase Cloud Messaging (Recommended)

FCM provides an HTTP/1.1-compatible REST API and handles APNs delivery
behind the scenes. This is the approach recommended in
[Supabase's official docs](https://supabase.com/docs/guides/functions/examples/push-notifications).

1. Create a Firebase project
2. Enable Cloud Messaging
3. Upload the APNs `.p8` key to Firebase (Project Settings > Cloud Messaging > APNs Authentication Key)
4. Create a Firebase service account and download the JSON key
5. Store the Firebase service account JSON as a Supabase secret
6. Update `sendPushNotification()` in the Edge Function to call FCM's HTTP v1 API instead of APNs directly
7. The iOS app would need to register FCM tokens instead of (or in addition to) raw APNs tokens

### Option 2: Expo Push Notification Service

Simpler setup, no Firebase needed. Expo handles APNs delivery.

### Option 3: OneSignal

Third-party push service with a REST API.

### After Fixing the Delivery

1. Redeploy Edge Function
2. Test end-to-end: INSERT into `generator_events` → notification on device
3. Remove `APNS_USE_SANDBOX=true` when building for production/TestFlight
4. Update `aps-environment` in entitlements from `development` to `production` for release builds (Xcode handles this automatically with automatic signing)

## Testing Commands

### Manual curl test (bypasses webhook, calls Edge Function directly)

```bash
curl -s -X POST \
  'https://lptqugsuefnccrwtbejw.supabase.co/functions/v1/push-notification' \
  -H 'Authorization: Bearer YOUR_SERVICE_ROLE_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"type":"INSERT","table":"generator_events","record":{"id":999,"previous_state":"normal","new_state":"outage","utility_voltage":0.0,"generator_voltage":240.5}}' | python3 -m json.tool
```

### SQL test event (triggers webhook)

```sql
INSERT INTO generator_events (previous_state, new_state, utility_voltage, generator_voltage)
VALUES ('normal', 'outage', 0.0, 240.5);
```

### Apple Push Notification Console (for testing device/token validity)

https://icloud.developer.apple.com/dashboard/notifications
- Team: Cluebucket Consulting, LLC
- Bundle ID: studio.offbyone.KohlerStat
- Environment: Sandbox
