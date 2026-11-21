// Typed wrappers around the Rust commands (src-tauri/src/lib.rs). The backend is only
// reached through Rust; see src-tauri/src/api.rs for why.
import { invoke } from "@tauri-apps/api/core";
import type { ScreenSummary } from "./screen/model";

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
  logged_in: boolean;
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
  /** false: the server has no password (nothing to log in to). */
  login: (password: string) => invoke<boolean>("login", { password }),
  /** A device key from the web app (Durum → Cihaz anahtarları); checked by the server first. */
  useDeviceKey: (key: string) => invoke<undefined>("use_device_key", { key }),
  logout: () => invoke<undefined>("logout"),
  hideChat: () => invoke<undefined>("hide_chat"),
  screenTime: () => invoke<ScreenSummary>("screen_time_today"),
  openConfigFolder: () => invoke<undefined>("open_config_folder"),
};
