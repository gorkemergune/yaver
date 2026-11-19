import { describe, expect, it } from "vitest";
import type { Team } from "../api";
import { tr } from "../i18n/tr";
import { conversationStore, errorMessage, fallbackColor, helpers, speakerOf } from "./model";

const team: Team = {
  coordinator: { id: "yaver", name: "Yaver", color: "#111111" },
  agents: [
    { id: "academic", name: "Friday", color: "#222222" },
    { id: "agenda", name: "Jarvis", color: null },
  ],
  onboarding: null,
};

describe("speakerOf", () => {
  it("uses the team's name and color", () => {
    expect(speakerOf(team, { speaker: "academic", agents: [] })).toEqual({ name: "Friday", color: "#222222" });
  });

  it("falls back to a stable palette color when the team has none", () => {
    const speaker = speakerOf(team, { speaker: "agenda", agents: [] });
    expect(speaker.color).toBe(fallbackColor("agenda"));
  });

  it("works before the team is loaded", () => {
    const reply = { speaker: "agenda", agents: [{ agent_id: "agenda", name: "Jarvis", reply: "" }] };
    expect(speakerOf(null, reply).name).toBe("Jarvis");
    expect(speakerOf(null, { speaker: "x", agents: [] }).name).toBe(tr.appName);
  });
});

describe("helpers", () => {
  it("lists delegated agents once, without the speaker", () => {
    const reply = {
      speaker: "yaver",
      agents: [
        { agent_id: "academic", name: "Friday", reply: "a" },
        { agent_id: "academic", name: "Friday", reply: "b" },
        { agent_id: "yaver", name: "Yaver", reply: "c" },
      ],
    };
    expect(helpers(team, reply).map((h) => h.name)).toEqual(["Friday"]);
  });
});

describe("errorMessage", () => {
  it("maps Rust error codes to Turkish", () => {
    expect(errorMessage({ code: "unreachable" })).toBe(tr.errors.unreachable);
    expect(errorMessage({ code: "http", status: 500 })).toBe(tr.errors.http(500));
    expect(errorMessage({ code: "something_new" })).toBe(tr.errors.unknown);
    expect(errorMessage("boom")).toBe(tr.errors.unknown);
  });
});

describe("conversationStore", () => {
  function memoryStorage(): Storage {
    const data = new Map<string, string>();
    return {
      get length() {
        return data.size;
      },
      clear: () => {
        data.clear();
      },
      getItem: (k) => data.get(k) ?? null,
      key: (i) => [...data.keys()][i] ?? null,
      removeItem: (k) => {
        data.delete(k);
      },
      setItem: (k, v) => {
        data.set(k, v);
      },
    };
  }

  it("remembers and forgets the conversation id", () => {
    const store = conversationStore(memoryStorage());
    expect(store.get()).toBeNull();
    store.set(42);
    expect(store.get()).toBe(42);
    store.set(null);
    expect(store.get()).toBeNull();
  });

  it("never throws when storage is broken", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    } as unknown as Storage;
    const store = conversationStore(broken);
    expect(store.get()).toBeNull();
    expect(() => {
      store.set(1);
    }).not.toThrow();
  });
});
