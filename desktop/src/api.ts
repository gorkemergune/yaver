// Typed wrappers around the Rust commands (src-tauri/src/lib.rs). The backend is only
// reached through Rust; see src-tauri/src/api.rs for why.
import { invoke } from "@tauri-apps/api/core";

export interface ApiError {
  code: string;
  status?: number;
  detail?: string;
}

export interface Settings {
  api_url: string;
  default_api_url: string;
  api_url_from_env: boolean;
  autostart: boolean;
}

export interface Change {
  entity: string;
  op: string;
  agent_id: string | null;
  data: Record<string, unknown>;
  undone: boolean;
}

/** `POST /api/chat` response (backend/app/api/chat.py: ChatResponse). */
export interface ChatResponse {
  conversation_id: number;
  reply: string;
  speaker: string;
  change_set_id: string | null;
  agents: { agent_id: string; name: string; reply: string }[];
  changes: Change[];
}

export interface TeamMember {
  id: string;
  name: string;
  color: string | null;
  domain?: string | null;
}

export interface Team {
  coordinator: TeamMember;
  agents: TeamMember[];
  onboarding: TeamMember | null;
  user_name?: string | null;
}

export const api = {
  settings: () => invoke<Settings>("get_settings"),
  setApiUrl: (url: string) => invoke<string>("set_api_url", { url }),
  setAutostart: (enabled: boolean) => invoke<boolean>("set_autostart", { enabled }),
  chat: (message: string, conversationId: number | null) =>
    invoke<ChatResponse>("send_chat", { message, conversationId }),
  undo: (changeSetId: string) => invoke<unknown>("undo_changes", { changeSetId }),
  team: () => invoke<Team>("get_team"),
  hideChat: () => invoke<undefined>("hide_chat"),
};
