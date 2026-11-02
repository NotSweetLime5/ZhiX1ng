import { expect, it } from 'vitest';
import { EMPTY_FORM, toAgentRequest, validateAgentForm } from './agent-form';
import type { Agent } from '@/types/agent';

it('rejects invalid numbers, empty models and duplicate fallback', () => {
  const errors = validateAgentForm({
    ...EMPTY_FORM,
    name: '助手',
    model_config_id: '',
    temperature: 'NaN',
    max_tokens: '1.5',
    max_iterations: '51',
  });
  expect(errors).toHaveProperty('model_config_id');
  expect(errors).toHaveProperty('temperature');
  expect(errors).toHaveProperty('max_tokens');
  expect(errors).toHaveProperty('max_iterations');
  expect(
    validateAgentForm({ ...EMPTY_FORM, name: '助手', model_config_id: '21', fallback_model_config_id: '21' }),
  ).toHaveProperty('fallback_model_config_id');
});
it('preserves existing tool config and unrelated execution config while clearing fallback explicitly', () => {
  const old = {
    config: { custom: true },
    tools: [{ tool_id: 3, config: { tz: 'Asia/Shanghai' } }],
  } as unknown as Agent;
  const form = { ...EMPTY_FORM, name: ' 学习助手 ', model_config_id: '21', tool_ids: [3, 4], kb_ids: [12] };
  expect(validateAgentForm(form)).toEqual({});
  const request = toAgentRequest(form, old);
  expect(request.tools).toEqual([{ tool_id: 3, config: { tz: 'Asia/Shanghai' } }, { tool_id: 4 }]);
  expect(request.config).toEqual({ custom: true, execution_mode: 'react' });
  expect(request.fallback_model_config_id).toBeNull();
  expect(request.name).toBe('学习助手');
});
