import { randomUUID } from "node:crypto";

import { lit, scalar, sql } from "./db";

/** Unique per call so reruns against the same database never collide. */
export const tag = (prefix: string): string => `${prefix} ${Date.now().toString(36)}`;

/** `(local date + offset) HH:MM` in Europe/Istanbul as a timestamptz expression. */
const localAt = (dayOffset: number, time: string): string =>
  `((((now() AT TIME ZONE 'Europe/Istanbul')::date + ${String(dayOffset)}) + time ${lit(time)}) AT TIME ZONE 'Europe/Istanbul')`;

/**
 * A finished chat turn without an LLM: a user message, Chrono's answer and a change set that
 * created a meeting tomorrow 10:00-11:00 (Europe/Istanbul). The same rows the coordinator would
 * write, so "Geri al" runs the real undo (POST /api/changes/{id}/undo).
 */
export function seedChangeSet(title: string): { conversationId: number; eventId: number; changeSetId: string } {
  const changeSetId = randomUUID();
  const iso = (column: string): string => `to_char(${column} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')`;
  const rows = sql(`
    WITH ev AS (
      INSERT INTO events (kind, title, start_at, end_at, all_day)
      VALUES ('meeting', ${lit(title)}, ${localAt(1, "10:00")}, ${localAt(1, "11:00")}, false)
      RETURNING id, kind, title, start_at, end_at, all_day, location, course_id, notes
    ), conv AS (
      INSERT INTO conversations (title, mode) VALUES (${lit(title)}, 'chat') RETURNING id
    ), um AS (
      INSERT INTO messages (conversation_id, role, content)
      SELECT id, 'user', ${lit(`yarın 10-11 ${title} ekle`)} FROM conv RETURNING id
    ), am AS (
      INSERT INTO messages (conversation_id, role, agent_id, content, change_set_id)
      SELECT conv.id, 'assistant', 'agenda', ${lit(`${title} yarın 10:00-11:00 olarak eklendi.`)}, ${lit(changeSetId)}::uuid
      FROM conv, um RETURNING id
    ), cl AS (
      INSERT INTO change_log (change_set_id, entity, entity_id, op, after_json, agent_id, message_id)
      SELECT ${lit(changeSetId)}::uuid, 'events', ev.id, 'create',
        jsonb_build_object('id', ev.id, 'kind', ev.kind, 'title', ev.title,
          'start_at', ${iso("ev.start_at")}, 'end_at', ${iso("ev.end_at")},
          'all_day', ev.all_day, 'location', ev.location, 'course_id', ev.course_id, 'notes', ev.notes),
        'agenda', am.id
      FROM ev, am RETURNING id
    )
    SELECT conv.id, ev.id FROM conv, ev, cl;
  `);
  const [conversationId, eventId] = rows[0] ?? [];
  return { conversationId: Number(conversationId), eventId: Number(eventId), changeSetId };
}

export function eventExists(id: number): boolean {
  return scalar(`SELECT count(*) FROM events WHERE id = ${String(id)};`) === "1";
}

/** A notebook entry and a finished inbox task for an employee (default: academic). */
export function seedEmployeeWork(note: string, task: string, employee = "academic"): void {
  sql(`
    INSERT INTO employee_notes (employee_id, content, source) VALUES (${lit(employee)}, ${lit(note)}, 'agent');
    INSERT INTO employee_tasks (employee_id, source, instruction, status, result, started_at, finished_at)
    VALUES (${lit(employee)}, 'user', ${lit(task)}, 'done', 'tamam', now() - interval '1 minute', now());
  `);
}

/** A plain one-off event on a local date offset from today. */
export function seedEvent(title: string, dayOffset: number, start = "14:00", end = "15:00"): number {
  return Number(
    scalar(`
      INSERT INTO events (kind, title, start_at, end_at, all_day)
      VALUES ('other', ${lit(title)}, ${localAt(dayOffset, start)}, ${localAt(dayOffset, end)}, false)
      RETURNING id;`),
  );
}
