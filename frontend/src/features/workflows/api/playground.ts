import { del, get, http, post } from "@/common/api/client";
import type { Document, Envelope, Page } from "@/common/types/api";
import type { PlaygroundProposal, PlaygroundSession, PlaygroundSessionSummary } from "../types/playground";

const root = "/workflow-playground/sessions/";
export const listSessions = (project: string, signal?: AbortSignal) => get<PlaygroundSessionSummary[]>(root, { project }, { signal });
export const getSession = (id: string, signal?: AbortSignal) => get<PlaygroundSession>(`${root}${id}/`, undefined, { signal });
export const createSession = (project: string) => post<PlaygroundSession>(root, { project });
export const deleteSession = (id: string) => del(`${root}${id}/`);
export const deleteSamples = (id: string) => http.delete<Envelope<PlaygroundSession>>(`${root}${id}/samples/delete/`).then((r) => r.data.data);
export const addDocument = (id: string, document_id: string) =>
  post<PlaygroundSession>(`${root}${id}/documents/`, { document_id });
export const addSample = (id: string, file: File) => {
  const form = new FormData();
  form.set("file", file);
  return post<PlaygroundSession>(`${root}${id}/samples/`, form);
};
export const generate = (id: string, data: { goal: string; workflow_type: string; refinement?: string }) =>
  post<PlaygroundSession>(`${root}${id}/generate/`, data);
export const saveProposal = (id: string, proposal: PlaygroundProposal) =>
  http.put<Envelope<PlaygroundSession>>(`${root}${id}/proposal/`, proposal).then((r) => r.data.data);
export const listDocuments = (dataset: string, search: string, signal?: AbortSignal) =>
  get<Page<Document>>("/documents/", { dataset, search, page_size: 100 }, { signal });
