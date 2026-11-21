import "./office.css";

import { useEffect, useRef, type CSSProperties } from "react";

import type { OfficeEmployee } from "../api/types";
import { tr } from "../i18n/tr";
import { DeskScreen } from "./DeskScreen";
import { SCENE_H, SCENE_W, deskOutline } from "./geometry";
import { figureView, looks, type Figure, type Staff } from "./model";
import chairBacks from "./scene/chairBacks.svg?raw";
import desks from "./scene/desks.svg?raw";
import desksFront from "./scene/desksFront.svg?raw";
import glassM from "./scene/glassM.svg?raw";
import glassY from "./scene/glassY.svg?raw";
import layer0 from "./scene/layer0.svg?raw";
import layout from "./scene/layout.json";
import yaverDesk from "./scene/yaverDesk.svg?raw";

const SVG: Record<string, string> = { layer0, yaverDesk, glassY, desks, desksFront, glassM, chairBacks };
// Inlined (not <img>): the window sky follows the page's --office-sky.
const LAYERS = layout.layers.map((layer) => ({ ...layer, svg: SVG[layer.name] ?? "" }));

interface Props {
  staff: Staff;
  figures: Record<string, Figure>;
  selected: string | null;
  onSelect: (id: string) => void;
  night: boolean; // the sky (local hour)
  offHours: boolean; // the office is closed (backend office hours)
  screen: string | null; // the desk screen zoomed in
  onOpenScreen: (id: string) => void;
  onCloseScreen: () => void;
}

export function OfficeScene({ staff, figures, selected, onSelect, night, offHours, screen, onOpenScreen, onCloseScreen }: Props) {
  const people = Object.values(staff); // Yaver first, then the agents.yaml order
  const frame = useRef<HTMLDivElement>(null);
  // narrow screens: start with the desks in view (the scene scrolls sideways)
  useEffect(() => {
    const el = frame.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth - el.clientWidth) * 0.55;
  }, []);
  const stage = {
    width: SCENE_W,
    height: SCENE_H,
    "--office-sky": night ? "#141c45" : "#8fbaf0",
  } as CSSProperties;
  return (
    <div className="yhq-frame" ref={frame}>
      <div className="yhq-stage" style={stage} role="group" aria-label={tr.office.sceneLabel}>
        {LAYERS.map((layer) => (
          <div key={layer.name} className="yhq-layer" style={{ zIndex: layer.z }} dangerouslySetInnerHTML={{ __html: layer.svg }} />
        ))}
        {(["back", "front"] as const).map((row) => (
          <Desks key={row} row={row} people={people} offHours={offHours} onOpen={onOpenScreen} />
        ))}
        {people.map((e) => {
          const f = figures[e.id];
          return f && !figureView(f, e, staff).hidden ? (
            <Person key={e.id} employee={e} figure={f} staff={staff} night={offHours} selected={selected === e.id} onSelect={onSelect} />
          ) : null;
        })}
        <div
          className="pointer-events-none absolute inset-0 rounded-[20px]"
          style={{ zIndex: 900, background: night ? "rgba(6,8,30,0.26)" : "rgba(0,0,0,0)" }}
        />
        <div className="yhq-list" role="list" aria-label={tr.office.listLabel}>
          {people.map((e) => {
            const f = figures[e.id];
            const status = f ? figureView(f, e, staff, offHours).status : "";
            return (
              <div role="listitem" key={e.id}>
                <button type="button" aria-pressed={selected === e.id} aria-label={`${e.name}, ${e.role} — ${status}`} onClick={() => {
                  onSelect(e.id);
                }}>
                  <span className="w-11 flex-none truncate font-bold" style={{ color: e.color }}>
                    {e.name}
                  </span>
                  <span className="min-w-0 flex-auto truncate">{status}</span>
                  {e.needs_user && <span className="yhq-alert" />}
                </button>
              </div>
            );
          })}
        </div>
        {screen && staff[screen] && (
          <DeskScreen
            employee={staff[screen]}
            status={figures[screen] ? figureView(figures[screen], staff[screen], staff, offHours).status : ""}
            onClose={onCloseScreen}
          />
        )}
      </div>
    </div>
  );
}

/** One desk row's screens: dark when its employee went home, lit for a night shift;
 *  clicking a desk zooms into its screen. Drawn just above that row's desks. */
function Desks({
  row,
  people,
  offHours,
  onOpen,
}: {
  row: "back" | "front";
  people: OfficeEmployee[];
  offHours: boolean;
  onOpen: (id: string) => void;
}) {
  const here = people.filter((e) => e.desk.row === row);
  return (
    <svg
      className="yhq-desks"
      width={SCENE_W}
      height={SCENE_H}
      viewBox={`0 0 ${String(SCENE_W)} ${String(SCENE_H)}`}
      style={{ zIndex: row === "back" ? 505 : 555 }}
      aria-hidden={here.length === 0}
    >
      {here.map((e) => {
        const state = e.activity === "off" ? "dark" : offHours && e.activity === "working" ? "lit" : "idle";
        return (
          <polygon
            key={e.id}
            points={deskOutline(row, e.desk.col)}
            className="yhq-desk"
            data-desk={e.id}
            data-state={state}
            style={{ "--yhq-accent": e.color } as CSSProperties}
            role="button"
            tabIndex={0}
            aria-label={tr.office.screen.desk(e.name)}
            onClick={() => {
              onOpen(e.id);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onOpen(e.id);
              }
            }}
          />
        );
      })}
    </svg>
  );
}

function Person({
  employee: e,
  figure: f,
  staff,
  night,
  selected,
  onSelect,
}: {
  employee: OfficeEmployee;
  figure: Figure;
  staff: Staff;
  night: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const v = figureView(f, e, staff, night);
  const { hair, head } = looks(e.id);
  const bubble = v.atDesk || v.alert || selected;
  return (
    <button
      type="button"
      className="yhq-agent"
      aria-label={`${e.name}, ${e.role} — ${v.status}`}
      aria-pressed={selected}
      data-employee={e.id}
      onClick={() => {
        onSelect(e.id);
      }}
      style={{ left: v.left, top: v.top, zIndex: v.z }}
    >
      {bubble && (
        <span className="yhq-bubble" style={{ color: e.color }}>
          {v.alert && <span className="yhq-alert" />}
          {selected && <span>{e.name}</span>}
          {v.atDesk && (
            <span>
              <span className="yhq-dot" />
              <span className="yhq-dot" />
              <span className="yhq-dot" />
            </span>
          )}
        </span>
      )}
      {selected && (
        <span className="absolute" style={{ left: -8, bottom: -6, width: 44, height: 16, borderRadius: "50%", border: `2px solid ${e.color}` }} />
      )}
      <span className={`absolute inset-0 block ${v.walking ? "yhq-walk" : ""}`}>
        <svg width="28" height="46" viewBox="0 0 28 46" aria-hidden="true">
          {v.sitting ? (
            <>
              <rect x="6" y="19" width="16" height="16" rx="6" fill={e.color} />
              <rect x="7" y="31" width="14" height="4" rx="2" fill="#000" opacity="0.25" />
            </>
          ) : (
            <>
              <ellipse cx="14" cy="43" rx="10" ry="3.5" fill="#000" opacity="0.4" />
              <rect x="6" y="19" width="16" height="22" rx="7" fill={e.color} />
            </>
          )}
          {v.fromBehind ? (
            <>
              <circle cx="14" cy="12" r="7.5" fill={hair} />
              <rect x="12" y="18" width="4" height="2" fill={head} />
            </>
          ) : (
            <>
              <rect x="9" y="23" width="10" height="3" rx="1.5" fill="#ffffff" opacity="0.35" />
              <circle cx="14" cy="12" r="7.5" fill={head} />
              <path d="M6.6 10.5 C7.5 4.5 20.5 4.5 21.4 10.5 C18 8.4 10 8.4 6.6 10.5 Z" fill={hair} />
            </>
          )}
          {v.hasCup && (
            <>
              <rect x="20" y="25" width="6" height="7" rx="1.5" fill="#f4f1ea" />
              <rect x="20" y="25" width="6" height="2" fill="#5a3a24" />
              <path className="yhq-steam" d="M22 22 q1.5 -2 0 -4 M24.5 22 q1.5 -2 0 -4" stroke="#ffffff" strokeWidth="0.8" fill="none" />
            </>
          )}
        </svg>
      </span>
    </button>
  );
}
