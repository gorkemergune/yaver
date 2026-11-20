import type { Member } from "../api/types";
import { Avatar } from "../design/parts";
import { roleOf } from "./roles";

/** The yaver's glowing orb: its own colour and icon. */
export function YaverAvatar({ member, id, size = 32 }: { member?: Member; id?: string; size?: number }) {
  const memberId = member?.id ?? id;
  return (
    <Avatar
      member={{ id: memberId ?? "yaver", role: roleOf(memberId), name: member?.name ?? "Yaver", color: member?.color ?? "#6366f1" }}
      shape="orb"
      size={size}
    />
  );
}
