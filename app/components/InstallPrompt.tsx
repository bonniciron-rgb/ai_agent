"use client";
import { useEffect, useState } from "react";

export function InstallPrompt() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const dismissed = localStorage.getItem("ethera-install-dismissed");
    if (dismissed) return;

    const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const isStandalone =
      (navigator as Navigator & { standalone?: boolean }).standalone === true ||
      window.matchMedia("(display-mode: standalone)").matches;

    if (isIOS && !isStandalone) {
      setVisible(true);
    }
  }, []);

  if (!visible) return null;

  function dismiss() {
    localStorage.setItem("ethera-install-dismissed", "1");
    setVisible(false);
  }

  return (
    <div
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        background: "#18181b",
        borderTop: "1px solid #3f3f46",
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "12px",
        fontSize: "14px",
        color: "#e4e4e7",
      }}
    >
      <span>
        Install Ethera: tap the share icon then &ldquo;Add to Home Screen&rdquo;
      </span>
      <button
        onClick={dismiss}
        style={{
          background: "none",
          border: "1px solid #52525b",
          borderRadius: "4px",
          color: "#a1a1aa",
          cursor: "pointer",
          padding: "4px 10px",
          fontSize: "13px",
          flexShrink: 0,
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
