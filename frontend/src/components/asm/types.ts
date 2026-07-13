import type { SqlResult } from "./SqlResultsTable";

export type Role = "user" | "assistant";

export interface Message {
  id: string;
  role: Role;
  content: string;
  createdAt: number;
  streaming?: boolean;
  sqlResult?: SqlResult;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  favorite?: boolean;
  updatedAt: number;
}
