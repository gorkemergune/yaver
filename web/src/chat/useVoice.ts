import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceState = "idle" | "recording" | "transcribing";

const BARS = 28;
const MAX_SECONDS = 60;
const MIN_SECONDS = 0.5; // shorter: an accidental tap, nothing is sent
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

function pickType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

function extension(type: string): string {
  if (type.includes("mp4")) return "m4a";
  if (type.includes("ogg")) return "ogg";
  return "webm";
}

/**
 * Push-to-talk recording -> POST /api/voice (Groq Whisper) -> text. `levels` (0..1, one
 * per bar) drive the waveform while recording. Errors are codes for tr.voice.errors.
 */
export function useVoice(onText: (text: string) => void, onError: (code: string) => void) {
  const [state, setState] = useState<VoiceState>("idle");
  const [levels, setLevels] = useState<number[]>(() => Array<number>(BARS).fill(0));
  const [seconds, setSeconds] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audio = useRef<AudioContext | null>(null);
  const frame = useRef(0);
  const startedAt = useRef(0);
  const send = useRef(true);

  const release = useCallback(() => {
    cancelAnimationFrame(frame.current);
    stream.current?.getTracks().forEach((track) => {
      track.stop();
    });
    stream.current = null;
    void audio.current?.close();
    audio.current = null;
    setLevels(Array<number>(BARS).fill(0));
  }, []);

  useEffect(() => release, [release]);

  const upload = useCallback(
    async (blob: Blob, type: string) => {
      setState("transcribing");
      const form = new FormData();
      form.append("audio", blob, `voice.${extension(type)}`);
      try {
        const response = await fetch("/api/voice", { method: "POST", body: form });
        const body = (await response.json().catch(() => ({}))) as { text?: string; detail?: { code?: string } };
        if (!response.ok || !body.text) {
          onError(body.detail?.code ?? "stt_unavailable");
        } else {
          onText(body.text);
        }
      } catch {
        onError("network");
      } finally {
        setState("idle");
      }
    },
    [onError, onText],
  );

  const stop = useCallback((andSend: boolean) => {
    send.current = andSend;
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  const start = useCallback(async () => {
    const type = pickType();
    // undefined outside a secure context (plain http from the phone), whatever the types say
    const devices = navigator.mediaDevices as MediaDevices | undefined;
    if (!type || !devices) {
      onError("unsupported");
      return;
    }
    let media: MediaStream;
    try {
      media = await devices.getUserMedia({ audio: true });
    } catch {
      onError("denied");
      return;
    }
    stream.current = media;
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(media, { mimeType: type });
    recorder.current = rec;
    rec.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    rec.onstop = () => {
      const length = (performance.now() - startedAt.current) / 1000;
      release();
      if (send.current && length >= MIN_SECONDS) {
        void upload(new Blob(chunks, { type }), type);
      } else {
        setState("idle");
      }
    };

    // waveform: loudness of the last few frames, newest on the right
    const context = new AudioContext();
    audio.current = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    context.createMediaStreamSource(media).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    let last = 0;
    const tick = (now: number): void => {
      if (now - last > 70) {
        last = now;
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const value of samples) sum += ((value - 128) / 128) ** 2;
        const level = Math.min(1, Math.sqrt(sum / samples.length) * 4);
        setLevels((prev) => [...prev.slice(1), level]);
        const elapsed = (performance.now() - startedAt.current) / 1000;
        setSeconds(Math.floor(elapsed));
        if (elapsed >= MAX_SECONDS) {
          stop(true);
          return;
        }
      }
      frame.current = requestAnimationFrame(tick);
    };

    send.current = true;
    startedAt.current = performance.now();
    setSeconds(0);
    rec.start(250);
    setState("recording");
    frame.current = requestAnimationFrame(tick);
  }, [onError, release, stop, upload]);

  return { state, levels, seconds, start, stop };
}
