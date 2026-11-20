import type { Role } from "../design/mock";

/** Which icon a yaver gets: by its id in agents.yaml (the example and default teams use
 * these ids); anyone else gets the coordinator's compass. */
export function roleOf(id: string | undefined): Role {
  if (id === "academic" || id === "agenda" || id === "discipline") return id;
  return "coordinator";
}
