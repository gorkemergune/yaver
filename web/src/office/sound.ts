/**
 * Light office sounds (O5): a soft tick when someone starts working, a two-note chime for
 * a meeting, a double ping when someone needs the user, a falling pair when a job is done.
 * Synthesized with Web Audio (no files), quiet, at most one every 300 ms, never in a hidden
 * tab. Off by default; the choice is kept in this browser (localStorage).
 */
import { useCallback, useSyncExternalStore } from "react";

import type { Cue } from "./model";

const KEY = "yaver.office.sound";
const GAP_MS = 300;
const VOLUME = 0.05;

// [frequency Hz, start s, length s]
const NOTES: Record<Cue, [number, number, number][]> = {
  work: [[1320, 0, 0.045]],
  meeting: [
    [660, 0, 0.12],
    [880, 0.12, 0.18],
  ],
  alert: [
    [988, 0, 0.09],
    [988, 0.15, 0.09],
  ],
  done: [
    [784, 0, 0.09],
    [523, 0.09, 0.14],
  ],
};

let enabled = read();
let audio: AudioContext | null = null;
let last = 0;
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === "on";
  } catch {
    return false;
  }
}

export function soundEnabled(): boolean {
  return enabled;
}

export function setSoundEnabled(on: boolean): void {
  enabled = on;
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // private mode: on for this page only
  }
  if (on) {
    // a click is the user gesture browsers want before audio may start
    try {
      audio ??= new AudioContext();
      void audio.resume();
    } catch {
      // no Web Audio: stays silent
    }
  }
  listeners.forEach((listener) => {
    listener();
  });
}

export function playCue(cue: Cue, now = performance.now()): boolean {
  if (!enabled || document.hidden || now - last < GAP_MS) return false;
  try {
    audio ??= new AudioContext();
    if (audio.state === "suspended") void audio.resume();
    const t0 = audio.currentTime + 0.01;
    for (const [frequency, start, length] of NOTES[cue]) {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = "sine";
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0, t0 + start);
      gain.gain.linearRampToValueAtTime(VOLUME, t0 + start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + start + length);
      osc.connect(gain).connect(audio.destination);
      osc.start(t0 + start);
      osc.stop(t0 + start + length + 0.02);
    }
  } catch {
    return false;
  }
  last = now;
  return true;
}

/** [on, toggle] for the sound switch in the office header. */
export function useSound(): [boolean, () => void] {
  const on = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    soundEnabled,
    () => false,
  );
  const toggle = useCallback(() => {
    setSoundEnabled(!soundEnabled());
    if (soundEnabled()) playCue("work");
  }, []);
  return [on, toggle];
}
