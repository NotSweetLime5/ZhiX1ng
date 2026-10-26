import { useCallback, useEffect, useState } from 'react';
import { createCase, createDataset, getEvaluation, listCases, listDatasets, startEvaluation } from '@/api/evaluation';
import type { EvalCase, EvalDataset, EvalRun } from '@/api/evaluation';
import { listAgents } from '@/api/agent';
import type { Agent } from '@/types/agent';
import { Button, Card, Input, PageHeader, Select, StatusBadge, Textarea } from '@/components/ui/primitives';
import { errMsg } from '@/lib/request';
import { toast } from '@/stores/ui';

export function EvaluationPage() {
  const [datasets, setDatasets] = useState<EvalDataset[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [dataset, setDataset] = useState('');
  const [agent, setAgent] = useState('0');
  const [name, setName] = useState('');
  const [question, setQuestion] = useState('');
  const [expected, setExpected] = useState('');
  const [tools, setTools] = useState('');
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [ds, ag] = await Promise.all([listDatasets(), listAgents({ page_size: 100 })]);
      setDatasets(ds);
      setAgents(ag.list);
    } catch (error) { toast.err(errMsg(error)); }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    setCases([]);
    setRun(null);
    if (dataset) void listCases(Number(dataset)).then(setCases).catch((e) => toast.err(errMsg(e)));
  }, [dataset]);

  const act = async (work: () => Promise<void>) => {
    setBusy(true);
    try { await work(); } catch (error) { toast.err(errMsg(error)); } finally { setBusy(false); }
  };

  return (
    <div className="page-container space-y-5">
      <PageHeader title="Agent 评估" desc="用预期答案片段、工具调用和检索命中检查 Agent 的执行结果" />
      <Card>
        <div className="flex gap-3">
          <Input aria-label="新评估集名称" placeholder="新评估集名称" value={name} onChange={(e) => setName(e.target.value)} />
          <Button disabled={!name.trim()} loading={busy} onClick={() => void act(async () => {
            const created = await createDataset(name.trim()); await reload(); setDataset(String(created.id)); setName('');
          })}>创建评估集</Button>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Select aria-label="评估集" value={dataset} onValueChange={(value) => setDataset(value)}>
            <option value="">选择评估集</option>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          <Select aria-label="Agent" value={agent} onValueChange={(value) => setAgent(value)}>
            <option value="0">默认助手</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
        </div>
      </Card>
      {dataset && (
        <Card>
          <Textarea aria-label="测试问题" rows={3} placeholder="测试问题" value={question} onChange={(e) => setQuestion(e.target.value)} />
          <Input className="mt-3" placeholder="预期答案包含的文本（可选）" value={expected} onChange={(e) => setExpected(e.target.value)} />
          <Input className="mt-3" placeholder="预期工具 code，逗号分隔（可选）" value={tools} onChange={(e) => setTools(e.target.value)} />
          <div className="mt-3 flex gap-3">
            <Button disabled={!question.trim()} loading={busy} onClick={() => void act(async () => {
              await createCase(Number(dataset), question.trim(), expected, tools.split(',').map((t) => t.trim()).filter(Boolean));
              setCases(await listCases(Number(dataset))); setQuestion(''); setExpected(''); setTools('');
            })}>添加用例</Button>
            <Button disabled={!cases.length} loading={busy} onClick={() => void act(async () => {
              setRun(await startEvaluation(Number(dataset), Number(agent)));
            })}>执行评估</Button>
          </div>
          <ul className="mt-4 space-y-2 text-sm text-fog">
            {cases.map((c) => <li key={c.id}>{c.question} <span className="text-ash">→ {c.expected_answer || '检查执行成功'}</span></li>)}
          </ul>
        </Card>
      )}
      {run && (
        <Card>
          <div className="flex items-center gap-3">
            <StatusBadge status={run.status} /><span className="text-sm text-fog">通过 {run.passed} / {run.total}</span>
            <Button variant="ghost" loading={busy} onClick={() => void act(async () => setRun(await getEvaluation(run.id)))}>刷新结果</Button>
          </div>
          {(run.status === 'pending' || run.status === 'running') && <p className="mt-3 text-sm text-ash">评估由后台 Worker 执行。</p>}
          {run.results?.map((result) => <div key={result.id} className="mt-3 border-t border-smoke py-3 text-sm text-fog">
            <span>{result.passed ? '通过' : '失败'}</span><p className="mt-1 whitespace-pre-wrap">{result.actual_answer || result.error}</p>
          </div>)}
        </Card>
      )}
    </div>
  );
}
