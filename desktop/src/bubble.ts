import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { isDrag, type Point } from "./drag";

// Press and move = drag the window (the OS takes over), press and release = toggle chat.
const bubble = document.getElementById("bubble");
if (!bubble) throw new Error("#bubble missing");

let pressedAt: Point | null = null;

bubble.addEventListener("mousedown", (event) => {
  if (event.button !== 0) return;
  pressedAt = { x: event.screenX, y: event.screenY };
});

bubble.addEventListener("mousemove", (event) => {
  if (!pressedAt || !isDrag(pressedAt, { x: event.screenX, y: event.screenY })) return;
  pressedAt = null;
  void getCurrentWindow().startDragging();
});

bubble.addEventListener("mouseup", (event) => {
  if (event.button !== 0 || !pressedAt) return;
  pressedAt = null;
  void invoke("toggle_chat");
});

bubble.addEventListener("mouseleave", () => {
  pressedAt = null;
});

// No browser context menu on the logo.
document.addEventListener("contextmenu", (event) => {
  event.preventDefault();
});
