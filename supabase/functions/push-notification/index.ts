import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

// APNs configuration from Supabase secrets
const APNS_KEY_ID = Deno.env.get("APNS_KEY_ID")!;
const APNS_TEAM_ID = Deno.env.get("APNS_TEAM_ID")!;
const APNS_PRIVATE_KEY = Deno.env.get("APNS_PRIVATE_KEY")!;
const APNS_TOPIC = "studio.offbyone.KohlerStat";
const APNS_HOST =
  Deno.env.get("APNS_USE_SANDBOX") === "true"
    ? "api.sandbox.push.apple.com"
    : "api.push.apple.com";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

// States that qualify as "outage-like" for notification purposes
const OUTAGE_STATES = ["outage", "critical"];

interface EventRecord {
  id: number;
  previous_state: string;
  new_state: string;
  utility_voltage: number | null;
  generator_voltage: number | null;
}

interface WebhookPayload {
  type: "INSERT";
  table: string;
  record: EventRecord;
}

/**
 * Determines whether a state transition should trigger a push notification.
 *
 * Notifiable transitions:
 * - Any state → outage
 * - Any state → critical
 * - outage/critical → normal (power restored)
 *
 * NOT notifiable:
 * - Any state → weekly_test
 * - weekly_test → normal
 */
function shouldNotify(previousState: string, newState: string): boolean {
  if (OUTAGE_STATES.includes(newState)) return true;
  if (newState === "normal" && OUTAGE_STATES.includes(previousState))
    return true;
  return false;
}

function buildNotificationContent(event: EventRecord): {
  title: string;
  body: string;
} {
  switch (event.new_state) {
    case "outage":
      return {
        title: "Power Outage",
        body: `Utility power lost. Generator running.${
          event.generator_voltage
            ? ` Gen: ${Math.round(event.generator_voltage)}V`
            : ""
        }`,
      };
    case "critical":
      return {
        title: "Generator Critical",
        body: `Utility power lost. Generator is NOT running.${
          event.utility_voltage
            ? ` Util: ${Math.round(event.utility_voltage)}V`
            : ""
        }`,
      };
    case "normal":
      return {
        title: "Power Restored",
        body: `Utility power restored. Generator standing down.${
          event.utility_voltage
            ? ` Util: ${Math.round(event.utility_voltage)}V`
            : ""
        }`,
      };
    default:
      return {
        title: "Generator Alert",
        body: `State changed to ${event.new_state}`,
      };
  }
}

/**
 * Creates a JWT for APNs token-based authentication using ES256.
 */
async function createAPNsJWT(): Promise<string> {
  const header = btoa(JSON.stringify({ alg: "ES256", kid: APNS_KEY_ID }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

  const now = Math.floor(Date.now() / 1000);
  const claims = btoa(JSON.stringify({ iss: APNS_TEAM_ID, iat: now }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

  const unsigned = `${header}.${claims}`;

  // Import the .p8 private key
  const pemContents = APNS_PRIVATE_KEY.replace(
    "-----BEGIN PRIVATE KEY-----",
    ""
  )
    .replace("-----END PRIVATE KEY-----", "")
    .replace(/\s/g, "");
  const keyData = Uint8Array.from(atob(pemContents), (c) => c.charCodeAt(0));

  const key = await crypto.subtle.importKey(
    "pkcs8",
    keyData,
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign"]
  );

  const signature = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    key,
    new TextEncoder().encode(unsigned)
  );

  const sigBase64 = btoa(String.fromCharCode(...new Uint8Array(signature)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

  return `${unsigned}.${sigBase64}`;
}

async function fetchActiveDeviceTokens(): Promise<string[]> {
  const response = await fetch(
    `${SUPABASE_URL}/rest/v1/device_tokens?select=token&active=eq.true`,
    {
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      },
    }
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch device tokens: ${response.status}`);
  }
  const rows: { token: string }[] = await response.json();
  return rows.map((r) => r.token);
}

// NOTE: This function currently sends directly to APNs via fetch (HTTP/1.1).
// APNs requires HTTP/2, and Supabase Edge Functions (Deno) only support HTTP/1.1.
// APNs accepts the connection and returns 200 but silently drops the notification.
// To fix this, replace direct APNs calls with an intermediary service that
// provides an HTTP/1.1-compatible API (e.g., FCM, Expo Push, or OneSignal).
// See: https://supabase.com/docs/guides/functions/examples/push-notifications
async function sendPushNotification(
  token: string,
  jwt: string,
  payload: object
): Promise<boolean> {
  try {
    const response = await fetch(`https://${APNS_HOST}/3/device/${token}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `bearer ${jwt}`,
        "apns-topic": APNS_TOPIC,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": "0",
      },
      body: JSON.stringify(payload),
    });

    if (response.status === 410) {
      // Token is no longer valid — mark inactive
      await fetch(
        `${SUPABASE_URL}/rest/v1/device_tokens?token=eq.${token}`,
        {
          method: "PATCH",
          headers: {
            apikey: SUPABASE_SERVICE_ROLE_KEY,
            Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ active: false }),
        }
      );
      return false;
    }

    return response.ok;
  } catch (error) {
    console.error(`Failed to send push to ${token}:`, error);
    return false;
  }
}

serve(async (req) => {
  try {
    const payload: WebhookPayload = await req.json();

    if (payload.type !== "INSERT" || payload.table !== "generator_events") {
      return new Response(JSON.stringify({ message: "Ignored" }), {
        status: 200,
      });
    }

    const event = payload.record;
    if (!shouldNotify(event.previous_state, event.new_state)) {
      return new Response(
        JSON.stringify({ message: "Not a notifiable transition" }),
        { status: 200 }
      );
    }

    const tokens = await fetchActiveDeviceTokens();
    if (tokens.length === 0) {
      return new Response(
        JSON.stringify({ message: "No registered devices" }),
        { status: 200 }
      );
    }

    const jwt = await createAPNsJWT();
    const { title, body } = buildNotificationContent(event);
    const apnsPayload = {
      aps: {
        alert: { title, body },
        sound: "default",
      },
    };

    const results = await Promise.allSettled(
      tokens.map((token) => sendPushNotification(token, jwt, apnsPayload))
    );

    const sent = results.filter(
      (r) => r.status === "fulfilled" && r.value === true
    ).length;

    return new Response(
      JSON.stringify({
        message: `Sent ${sent}/${tokens.length} notifications`,
      }),
      { status: 200 }
    );
  } catch (error) {
    console.error("Push notification error:", error);
    return new Response(
      JSON.stringify({ error: (error as Error).message }),
      { status: 500 }
    );
  }
});
