import { ApiClient } from "./client";

export type SessionRole = "viewer" | "investigator" | "approver" | "admin";
export type Session = { token_id: string; role: SessionRole };
export const getSession = (client: ApiClient) => client.get<Session>("/v1/me");