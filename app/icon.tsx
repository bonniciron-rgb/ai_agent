import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    <div
      style={{
        background: "#0E2138",
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#1F6B82",
        fontSize: 22,
        fontWeight: 800,
      }}
    >
      E
    </div>,
    { ...size }
  );
}
