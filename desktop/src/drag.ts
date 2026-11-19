/** Tells a click from the start of a drag: the pointer has to travel a few pixels. */
export const DRAG_THRESHOLD_PX = 4;

export interface Point {
  x: number;
  y: number;
}

export function isDrag(from: Point, to: Point, threshold = DRAG_THRESHOLD_PX): boolean {
  return Math.hypot(to.x - from.x, to.y - from.y) > threshold;
}
