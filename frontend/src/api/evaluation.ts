import { http } from '@/lib/request';

export interface EvalDataset {
  id: number;
  name: string;
  description: string;
  case_count: number;
}

export interface EvalCase {
  id: number;
  question: string;
  expected_answer: string;
  expected_tools: string[];
}

export interface EvalRun {
  id: number;
  status: string;
  total: number;
  passed: number;
  metrics: Record<string, unknown>;
  results: { id: number; actual_answer: string; passed: boolean; error: string; scores: Record<string, unknown> }[];
}

export const listDatasets = () => http.get<EvalDataset[]>('/admin/eval/datasets');
export const createDataset = (name: string) => http.post<EvalDataset>('/admin/eval/datasets', { name });
export const listCases = (id: number) => http.get<EvalCase[]>(`/admin/eval/datasets/${id}/cases`);
export const createCase = (id: number, question: string, expectedAnswer: string, expectedTools: string[]) =>
  http.post<EvalCase>(`/admin/eval/datasets/${id}/cases`, { question, expected_answer: expectedAnswer, expected_tools: expectedTools });
export const startEvaluation = (datasetId: number, agentId: number) =>
  http.post<EvalRun>('/admin/eval/runs', { dataset_id: datasetId, agent_id: agentId });
export const getEvaluation = (id: number) => http.get<EvalRun>(`/admin/eval/runs/${id}`);
