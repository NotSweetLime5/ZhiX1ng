import type { Agent, AgentReq } from '@/types/agent';

export interface AgentForm {
  name: string;
  description: string;
  type: Agent['type'];
  execution_mode: 'react' | 'plan';
  system_prompt: string;
  model_config_id: string;
  fallback_model_config_id: string;
  temperature: string;
  max_tokens: string;
  max_iterations: string;
  memory_window: string;
  memory_enabled: boolean;
  memory_long_enabled: boolean;
  kb_ids: number[];
  tool_ids: number[];
}
export const EMPTY_FORM: AgentForm = {
  name: '',
  description: '',
  type: 'expert',
  execution_mode: 'react',
  system_prompt: '',
  model_config_id: '',
  fallback_model_config_id: '',
  temperature: '0.7',
  max_tokens: '4096',
  max_iterations: '10',
  memory_window: '20',
  memory_enabled: true,
  memory_long_enabled: false,
  kb_ids: [],
  tool_ids: [],
};
export type FormErrors = Partial<Record<keyof AgentForm, string>>;
export function toForm(a: Agent): AgentForm {
  return {
    ...EMPTY_FORM,
    name: a.name,
    description: a.description,
    type: a.type,
    execution_mode: a.config?.execution_mode ?? 'react',
    system_prompt: a.system_prompt,
    model_config_id: String(a.model_config_id),
    fallback_model_config_id: a.fallback_model_config_id ? String(a.fallback_model_config_id) : '',
    temperature: String(a.temperature),
    max_tokens: String(a.max_tokens),
    max_iterations: String(a.max_iterations),
    memory_window: String(a.memory_window),
    memory_enabled: a.memory_enabled,
    memory_long_enabled: a.memory_long_enabled,
    kb_ids: [...a.kb_ids],
    tool_ids: a.tools.map((t) => t.tool_id),
  };
}
export function validateAgentForm(f: AgentForm): FormErrors {
  const errors: FormErrors = {};
  if (!f.name.trim() || f.name.trim().length > 128) errors.name = '名称需要 1～128 个字符';
  for (const [key, min, max, integer] of [
    ['model_config_id', 1, Number.MAX_SAFE_INTEGER, true],
    ['temperature', 0, 2, false],
    ['max_tokens', 1, 128000, true],
    ['max_iterations', 1, 50, true],
    ['memory_window', 1, 100, true],
  ] as const) {
    const value = Number(f[key]);
    if (
      !f[key].trim() ||
      !Number.isFinite(value) ||
      value < min ||
      value > max ||
      (integer && !Number.isInteger(value))
    ) {
      errors[key] =
        key === 'model_config_id'
          ? '请选择可用的对话模型'
          : `请输入 ${min}～${max} 的${integer ? '整数' : '数值'}`;
    }
  }
  if (
    f.fallback_model_config_id &&
    (f.fallback_model_config_id === f.model_config_id ||
      !Number.isSafeInteger(Number(f.fallback_model_config_id)) ||
      Number(f.fallback_model_config_id) < 1)
  ) {
    errors.fallback_model_config_id = '备用模型应选择不同的有效模型';
  }
  return errors;
}
export function toAgentRequest(f: AgentForm, previous?: Agent | null): AgentReq {
  return {
    name: f.name.trim(),
    description: f.description.trim(),
    type: f.type,
    system_prompt: f.system_prompt,
    model_config_id: Number(f.model_config_id),
    fallback_model_config_id: f.fallback_model_config_id ? Number(f.fallback_model_config_id) : null,
    temperature: Number(f.temperature),
    max_tokens: Number(f.max_tokens),
    max_iterations: Number(f.max_iterations),
    memory_window: Number(f.memory_window),
    memory_enabled: f.memory_enabled,
    memory_long_enabled: f.memory_long_enabled,
    kb_ids: f.kb_ids,
    tools: f.tool_ids.map((id) => previous?.tools.find((t) => t.tool_id === id) ?? { tool_id: id }),
    config: { ...previous?.config, execution_mode: f.execution_mode },
  };
}
