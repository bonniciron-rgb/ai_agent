"use client";
import { useEffect, useState } from "react";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) {
    output[i] = raw.charCodeAt(i);
  }
  return output;
}

type PushState = "unsupported" | "denied" | "subscribed" | "unsubscribed" | "loading";

export function PushSubscribeButton() {
  const [state, setState] = useState<PushState>("loading");

  useEffect(() => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setState("unsupported");
      return;
    }
    if (Notification.permission === "denied") {
      setState("denied");
      return;
    }
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => {
        if (sub && Notification.permission === "granted") {
          setState("subscribed");
        } else {
          setState("unsubscribed");
        }
      })
      .catch(() => setState("unsubscribed"));
  }, []);

  async function enable() {
    setState("loading");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "denied" : "unsubscribed");
        return;
      }
      const keyRes = await fetch("/api/push/vapid-public-key");
      if (!keyRes.ok) {
        setState("unsubscribed");
        return;
      }
      const { key } = await keyRes.json();
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key).buffer as ArrayBuffer,
      });
      const json = sub.toJSON();
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: json.endpoint,
          keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth },
        }),
      });
      setState("subscribed");
    } catch {
      setState("unsubscribed");
    }
  }

  if (state === "unsupported" || state === "loading") return null;

  if (state === "denied") {
    return (
      <span
        style={{
          fontSize: "12px",
          color: "#71717a",
          padding: "4px 8px",
        }}
      >
        Notifications blocked
      </span>
    );
  }

  if (state === "subscribed") {
    return (
      <span
        style={{
          fontSize: "12px",
          color: "#6366f1",
          padding: "4px 8px",
        }}
      >
        Push enabled
      </span>
    );
  }

  return (
    <button
      onClick={enable}
      style={{
        background: "#1e1b4b",
        border: "1px solid #4f46e5",
        borderRadius: "4px",
        color: "#a5b4fc",
        cursor: "pointer",
        fontSize: "13px",
        padding: "4px 12px",
      }}
    >
      Enable notifications
    </button>
  );
}
