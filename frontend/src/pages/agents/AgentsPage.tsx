/**
 * Agent 配置管理页 —— 平台 Agent（host 路由 / expert 专项）的增删改查。
 *
 * 职责：
 * 1. 拉取 Agent 清单，卡片网格展示名称、类型、参数摘要与工具/知识库绑定数；
 * 2. 新建与编辑复用同一 Modal 表单（编辑预填），工具绑定用 checkbox 多选；
 * 3. 删除走 ConfirmDialog 二次确认，预置 Agent 禁止删除。
 */
import { useNavigate } from 'react-router-dom';
import { allKBs } from '@/api/kb';
import { listChatModels } from '@/api/chat';
import { useAuth } from '@/stores/auth';
import {
  EMPTY_FORM,
  toForm,
  toAgentRequest,
  validateAgentForm,
  type AgentForm,
  type FormErrors,
} from '@/lib/agent-form';
import type { KnowledgeBase } from '@/types/kb';
import type { ChatModelItem } from '@/types/chat';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Select,
  Spinner,
  Textarea,
} from '@/components/ui/primitives';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { createAgent, deleteAgent, listAgents, listTools, updateAgent } from '@/api/agent';
import type { Agent, Tool } from '@/types/agent';
import { errMsg } from '@/lib/request';
import { toast } from '@/stores/ui';
import { staggerEnter } from '@/lib/gsap';
import { Icon } from '@/components/ui/Icon';

/* ---- 常量映射 ---- */

/** Agent 类型 → Badge 文案 / 色调 */
const TYPE_BADGE: Record<Agent['type'], { text: string; tone: 'violet' | 'teal' }> = {
  host: { text: 'Host·路由', tone: 'violet' },
  expert: { text: 'Expert·专项', tone: 'teal' },
};

export function AgentsPage() {
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const [models, setModels] = useState<ChatModelItem[]>([]);
  const [kbs, setKBs] = useState<KnowledgeBase[]>([]);
  const [optionLoading, setOptionLoading] = useState(false);
  const [optionError, setOptionError] = useState('');
  const [optionVersion, setOptionVersion] = useState(0);
  const [errors, setErrors] = useState<FormErrors>({});
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [tools, setTools] = useState<Tool[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [form, setForm] = useState<AgentForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [delTarget, setDelTarget] = useState<Agent | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  /** 拉取 Agent 清单（单页 100 条足够管理场景） */
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAgents({ page: 1, page_size: 100 });
      setAgents(data.list);
    } catch (e) {
      toast.err(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 列表挂载 / 刷新后子项交错入场（GSAP）
  useEffect(() => {
    const els = gridRef.current ? Array.from(gridRef.current.children) : [];
    if (els.length === 0) return;
    const tween = staggerEnter(els);
    return () => {
      tween.kill();
    };
  }, [agents]);

  useEffect(() => {
    if (!modalOpen) return;
    let active = true;
    setOptionLoading(true);
    setOptionError('');
    const loadTools = async () => {
      const result: Tool[] = [];
      for (let page = 1; ; page++) {
        const data = await listTools({ page, page_size: 100 });
        result.push(...data.list);
        if (result.length >= data.total || !data.list.length) return result;
      }
    };
    void Promise.all([listChatModels(), allKBs(), loadTools()])
      .then(([m, k, t]) => {
        if (active) {
          setModels(m);
          setKBs(k);
          setTools(t);
        }
      })
      .catch((e) => {
        if (active) setOptionError(errMsg(e));
      })
      .finally(() => {
        if (active) setOptionLoading(false);
      });
    return () => {
      active = false;
    };
  }, [modalOpen, optionVersion]);

  const openCreate = () => {
    setErrors({});
    setEditing(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  };

  const openEdit = (a: Agent) => {
    setErrors({});
    setEditing(a);
    setForm(toForm(a));
    setModalOpen(true);
  };

  /** 通用表单字段写入 */
  const setField = <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  /** 工具勾选切换 */
  const toggleTool = (id: number) => {
    setForm((f) => ({
      ...f,
      tool_ids: f.tool_ids.includes(id) ? f.tool_ids.filter((t) => t !== id) : [...f.tool_ids, id],
    }));
  };

  const trial = (id: number) => navigate(`/chat?agent=${id}`);
  const submit = async (tryChat = false) => {
    if (saving || optionLoading || optionError) return;
    const next = validateAgentForm(form);
    if (!models.some((m) => m.id === Number(form.model_config_id)))
      next.model_config_id = '请选择当前可用模型';
    if (form.fallback_model_config_id && !models.some((m) => m.id === Number(form.fallback_model_config_id)))
      next.fallback_model_config_id = '备用模型已不可用，请重新选择';
    if (form.kb_ids.some((id) => !kbs.some((k) => k.id === id)))
      next.kb_ids = '部分知识库已不可用，请取消选择或重新绑定';
    if (form.tool_ids.some((id) => !tools.some((t) => t.id === id)))
      next.tool_ids = '部分工具已不可用，请取消选择或重新绑定';
    setErrors(next);
    if (Object.keys(next).length) return;
    setSaving(true);
    try {
      const req = toAgentRequest(form, editing);
      const saved = editing ? await updateAgent(editing.id, req) : await createAgent(req);
      toast.ok(editing ? 'Agent 已更新' : 'Agent 已创建');
      setModalOpen(false);
      if (tryChat) trial(saved.id);
      else await refresh();
    } catch (e) {
      toast.err(errMsg(e));
    } finally {
      setSaving(false);
    }
  };
  const fieldError = (key: keyof AgentForm) =>
    errors[key] ? (
      <p role="alert" className="mt-1 text-xs text-coral">
        {errors[key]}
      </p>
    ) : null;

  const confirmDelete = async () => {
    if (!delTarget) return;
    try {
      await deleteAgent(delTarget.id);
      toast.ok('Agent 已删除');
      setDelTarget(null);
      await refresh();
    } catch (e) {
      toast.err(errMsg(e));
    }
  };

  return (
    <div className="page-container">
      <PageHeader
        title="Agent 管理"
        desc="为不同任务配置专属智能体，连接模型、工具与知识库。"
        action={<Button onClick={openCreate}>＋ 新建 Agent</Button>}
      />

      {loading ? (
        <div className="flex justify-center py-20">
          <Spinner className="h-6 w-6 text-lime" />
        </div>
      ) : agents.length === 0 ? (
        <EmptyState title="暂无 Agent" hint="点击右上角「新建 Agent」，创建第一个 Agent 配置" />
      ) : (
        <div ref={gridRef} className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {agents.map((a) => (
            <Card key={a.id} className="flex flex-col gap-3">
              {/* 名称 + 预置标记 + 类型徽标 */}
              <div className="flex items-center gap-3">
                <span
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border ${a.type === 'host' ? 'border-violet/20 bg-violet/10 text-violet' : 'border-teal/20 bg-teal/10 text-teal'}`}
                >
                  <Icon name={a.type === 'host' ? 'workflow' : 'agent'} className="h-5 w-5" />
                </span>
                <div className="min-w-0 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-base font-semibold text-bone">{a.name}</h3>
                    {a.is_preset && <Badge tone="gray">预置</Badge>}
                  </div>
                  <Badge tone={TYPE_BADGE[a.type].tone}>{TYPE_BADGE[a.type].text}</Badge>
                </div>
              </div>

              {/* 描述（最多两行） */}
              <p className="line-clamp-2 text-sm leading-relaxed text-fog">{a.description || '暂无描述'}</p>

              {/* 参数摘要 */}
              <div className="grid grid-cols-3 gap-2 rounded-lg border border-smoke/40 bg-carbon/60 px-3 py-2 text-center">
                <div>
                  <p className="text-sm text-bone">{a.temperature}</p>
                  <p className="text-[10px] text-ash">温度</p>
                </div>
                <div>
                  <p className="text-sm text-bone">{a.max_tokens}</p>
                  <p className="text-[10px] text-ash">Max Tokens</p>
                </div>
                <div>
                  <p className="text-sm text-bone">{a.max_iterations}</p>
                  <p className="text-[10px] text-ash">迭代上限</p>
                </div>
              </div>

              {/* 绑定计数 */}
              <div className="flex gap-4 text-xs text-ash">
                <span>
                  工具 <span className="text-fog">{a.tools.length}</span>
                </span>
                <span>
                  知识库 <span className="text-fog">{a.kb_ids.length}</span>
                </span>
              </div>

              {/* 操作区：编辑始终可用；预置 Agent 禁止删除 */}
              <div className="mt-auto flex justify-end gap-2 border-t border-smoke/40 pt-3">
                <Button variant="ghost" className="px-3 py-1 text-xs" onClick={() => trial(a.id)}>
                  试聊
                </Button>
                <Button
                  variant="ghost"
                  className="px-3 py-1 text-xs"
                  disabled={a.creator_id !== undefined && a.creator_id !== user?.id}
                  onClick={() => openEdit(a)}
                >
                  编辑
                </Button>
                <Button
                  variant="danger"
                  className="px-3 py-1 text-xs"
                  disabled={a.is_preset}
                  title={a.is_preset ? '预置 Agent 不可删除' : undefined}
                  onClick={() => setDelTarget(a)}
                >
                  删除
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* 新建 / 编辑 Modal（复用同一表单，编辑时预填） */}
      <Modal
        open={modalOpen}
        title={editing ? `编辑 Agent · ${editing.name}` : '新建 Agent'}
        onClose={() => {
          if (!saving) setModalOpen(false);
        }}
        width="max-w-2xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              取消
            </Button>
            <Button disabled={optionLoading || !!optionError} loading={saving} onClick={() => void submit()}>
              {editing ? '保存修改' : '创建'}
            </Button>
            <Button
              disabled={optionLoading || !!optionError}
              loading={saving}
              onClick={() => void submit(true)}
            >
              保存并试聊
            </Button>
          </>
        }
      >
        <form
          noValidate
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {optionLoading && (
            <p className="flex items-center gap-2 text-xs text-ash">
              <Spinner />
              加载可用模型、知识库与工具…
            </p>
          )}
          {optionError && (
            <div role="alert" className="text-sm text-coral">
              {optionError}
              <Button variant="ghost" type="button" onClick={() => setOptionVersion((n) => n + 1)}>
                重新加载
              </Button>
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="field-label">名称 *</label>
              <Input
                value={form.name}
                onChange={(e) => setField('name', e.target.value)}
                aria-label="Agent 名称"
                aria-invalid={!!errors.name}
                maxLength={128}
                placeholder="如：客服专员"
              />
              {fieldError('name')}
            </div>
            <div>
              <label className="field-label">类型</label>
              <Select
                aria-label="智能体类型"
                value={form.type}
                onValueChange={(value) => setField('type', value as Agent['type'])}
              >
                <option value="expert">expert · 专项执行</option>
                <option value="host">host · 路由聚合</option>
              </Select>
            </div>
          </div>

          {form.type === 'expert' && (
            <div>
              <label className="field-label">执行模式</label>
              <Select
                aria-label="执行方式"
                value={form.execution_mode}
                onValueChange={(value) => setField('execution_mode', value as 'react' | 'plan')}
              >
                <option value="react">直接执行</option>
                <option value="plan">先规划，再逐步执行</option>
              </Select>
            </div>
          )}

          <div>
            <label className="field-label">描述</label>
            <Input
              value={form.description}
              onChange={(e) => setField('description', e.target.value)}
              placeholder="Agent 职责说明"
            />
          </div>

          <div>
            <label className="field-label">System Prompt</label>
            <Textarea
              rows={6}
              value={form.system_prompt}
              onChange={(e) => setField('system_prompt', e.target.value)}
              placeholder="设定 Agent 的角色、能力边界与输出规范"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">对话模型 *</label>
              <Select
                aria-label="对话模型"
                value={form.model_config_id}
                disabled={optionLoading}
                onValueChange={(value) => setField('model_config_id', value)}
              >
                <option value="">选择对话模型</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} · {m.provider}
                  </option>
                ))}
                {form.model_config_id && !models.some((m) => String(m.id) === form.model_config_id) && (
                  <option value={form.model_config_id}>当前模型不可用，请重新选择</option>
                )}
              </Select>
              {fieldError('model_config_id')}
              {!optionLoading && !models.length && (
                <p className="mt-1 text-xs text-coral">暂无可用对话模型，请联系管理员配置。</p>
              )}
            </div>
            <div>
              <label className="field-label">备用模型</label>
              <Select
                aria-label="备用模型"
                value={form.fallback_model_config_id}
                onValueChange={(value) => setField('fallback_model_config_id', value)}
              >
                <option value="">不使用备用模型</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} · {m.provider}
                  </option>
                ))}
              </Select>
              {fieldError('fallback_model_config_id')}
            </div>
            <div>
              <label className="field-label">Temperature</label>
              <Input
                type="number"
                step="0.1"
                min={0}
                max={2}
                aria-label="Temperature"
                value={form.temperature}
                onChange={(e) => setField('temperature', e.target.value)}
                placeholder="0.7"
              />
              {fieldError('temperature')}
            </div>
            <div>
              <label className="field-label">Max Tokens</label>
              <Input
                type="number"
                aria-label="Max Tokens"
                min={1}
                max={128000}
                step={1}
                value={form.max_tokens}
                onChange={(e) => setField('max_tokens', e.target.value)}
                placeholder="2048"
              />
              {fieldError('max_tokens')}
            </div>
            <div>
              <label className="field-label">最大迭代次数</label>
              <Input
                type="number"
                aria-label="最大迭代次数"
                min={1}
                max={50}
                step={1}
                value={form.max_iterations}
                onChange={(e) => setField('max_iterations', e.target.value)}
                placeholder="5"
              />
              {fieldError('max_iterations')}
            </div>
          </div>

          <div>
            <label className="field-label">近期消息窗口</label>
            <Input
              aria-label="近期消息窗口"
              type="number"
              min={1}
              max={100}
              step={1}
              value={form.memory_window}
              onChange={(e) => setField('memory_window', e.target.value)}
            />
            {fieldError('memory_window')}
            <p className="mt-1 text-xs text-ash">保留最近 1～100 条消息作为短期上下文。</p>
          </div>
          {/* 记忆开关 */}
          <div className="grid grid-cols-2 gap-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-mist">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-lime"
                checked={form.memory_enabled}
                onChange={(e) => setField('memory_enabled', e.target.checked)}
              />
              启用短期记忆
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-mist">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-lime"
                checked={form.memory_long_enabled}
                onChange={(e) => setField('memory_long_enabled', e.target.checked)}
              />
              启用长期记忆
            </label>
          </div>

          <fieldset>
            <legend className="field-label">绑定知识库</legend>
            <div className="max-h-48 space-y-2 overflow-y-auto rounded-xl border border-smoke/50 p-3">
              {kbs.map((kb) => (
                <label
                  key={kb.id}
                  className="flex cursor-pointer items-start gap-3 rounded-lg p-2 hover:bg-graphite"
                >
                  <input
                    type="checkbox"
                    className="mt-1 accent-lime"
                    checked={form.kb_ids.includes(kb.id)}
                    onChange={() =>
                      setField(
                        'kb_ids',
                        form.kb_ids.includes(kb.id)
                          ? form.kb_ids.filter((id) => id !== kb.id)
                          : [...form.kb_ids, kb.id],
                      )
                    }
                  />
                  <span>
                    <span className="text-sm text-bone">{kb.name}</span>
                    <span className="mt-1 block text-xs text-ash">
                      {kb.doc_count} 篇文档 · {kb.description || '暂无描述'}
                    </span>
                  </span>
                </label>
              ))}
              {form.kb_ids
                .filter((id) => !kbs.some((kb) => kb.id === id))
                .map((id) => (
                  <label key={id} className="flex gap-2 text-sm text-coral">
                    <input
                      type="checkbox"
                      checked
                      onChange={() =>
                        setField(
                          'kb_ids',
                          form.kb_ids.filter((value) => value !== id),
                        )
                      }
                    />
                    不可用的知识库 #{id}（取消勾选可移除）
                  </label>
                ))}
              {!optionLoading && !kbs.length && (
                <p className="text-xs text-ash">暂无知识库，可以先保存助手，再到知识库页面上传资料。</p>
              )}
            </div>
            {fieldError('kb_ids')}
          </fieldset>

          {/* 工具绑定：checkbox 列表，危险工具带 coral 警示 */}
          <div>
            <label className="field-label">工具绑定</label>
            {fieldError('tool_ids')}
            <div className="max-h-40 space-y-0.5 overflow-y-auto rounded-lg border border-smoke/60 bg-graphite/40 p-2">
              {tools.map((t) => (
                <label
                  key={t.id}
                  className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-obsidian"
                >
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-lime"
                    checked={form.tool_ids.includes(t.id)}
                    onChange={() => toggleTool(t.id)}
                  />
                  <span className="text-bone">{t.name}</span>
                  <span className="font-mono text-ash">{t.code}</span>
                  {t.is_dangerous && (
                    <Badge tone="coral" className="ml-auto">
                      危险
                    </Badge>
                  )}
                </label>
              ))}
              {form.tool_ids
                .filter((id) => !tools.some((t) => t.id === id))
                .map((id) => (
                  <label key={id} className="flex gap-2 text-xs text-coral">
                    <input type="checkbox" checked onChange={() => toggleTool(id)} />
                    不可用工具 #{id}（取消勾选可移除）
                  </label>
                ))}
              {tools.length === 0 && <p className="py-2 text-center text-xs text-ash">暂无可用工具</p>}
            </div>
          </div>
        </form>
      </Modal>

      {/* 删除二次确认 */}
      <ConfirmDialog
        open={delTarget !== null}
        title="删除 Agent"
        content={`确认删除 Agent「${delTarget?.name ?? ''}」？删除后不可恢复。`}
        danger
        confirmText="删除"
        onCancel={() => setDelTarget(null)}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
