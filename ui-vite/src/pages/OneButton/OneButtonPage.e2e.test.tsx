import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';

import type { DecisionResponse } from '../../services/decisionApi';

const { runDecisionPipelineMock, chatFlowPayload } = vi.hoisted(() => ({
  runDecisionPipelineMock: vi.fn(),
  chatFlowPayload: {
    profile_raw: {
      age: '22',
      location: 'Ha Noi',
      mobility: 'co',
      languages: 'English',
      current_field: 'technology',
    },
    skills_input: {
      skills_list: 'python, sql',
      years_used: '2',
      real_world_used: 'co',
      certified: 'co',
      skill_levels: 'nang cao',
    },
    interest_raw: {
      preferred_industry: 'technology',
      excluded_industry: '',
      work_style: 'doc lap',
      work_preference: 'cong nghe',
      environment: 'sang tao',
      motivation: 'growth',
    },
    education_input: {
      degree_level: 'dai hoc',
      expected_salary: '20',
      priority_weight: 'thu nhap',
      training_horizon_months: '12',
      field_of_study: 'Computer Science',
    },
    experience_data: {
      years: '2',
    },
    goal_raw: {
      explanation_depth: 'chi tiet',
      roadmap_horizon: '3 nam',
      consent_flag: 'co',
      save_profile: 'khong',
      priority: 'thu nhap',
      target_position: 'software engineer',
    },
  },
}));

vi.mock('../../services/decisionApi', async () => {
  const actual = await vi.importActual<typeof import('../../services/decisionApi')>(
    '../../services/decisionApi',
  );
  return {
    ...actual,
    runDecisionPipeline: (...args: unknown[]) => runDecisionPipelineMock(...args),
  };
});

vi.mock('../../hooks/useTaxonomy', () => ({
  useTaxonomy: () => ({
    skills: [{ id: 'python', label: 'Python' }],
    interests: [{ id: 'technology', label: 'technology' }],
    education: [{ id: 'bachelor', label: 'Bachelor' }],
    loading: false,
  }),
}));

vi.mock('../../components/PipelineTimeline/PipelineTimeline', () => ({
  __esModule: true,
  default: () => null,
}));

vi.mock('../../components/RuleHitHistory/RuleHitHistory', () => ({
  __esModule: true,
  default: () => null,
}));

vi.mock('../../components/VersionTrace/VersionTrace', () => ({
  __esModule: true,
  default: () => null,
}));

vi.mock('../../components/features/ChatFlow/ChatFlow', () => ({
  __esModule: true,
  default: ({ onComplete }: { onComplete: (data: unknown) => void }) => (
    <button
      type="button"
      data-testid="mock-chatflow-submit"
      onClick={() => onComplete(chatFlowPayload)}
    >
      Mock ChatFlow Submit
    </button>
  ),
}));

import OneButtonPage from './OneButtonPage';

const structuredBase = {
  summary: 'Structured summary: profile and scoring are aligned for the recommended career.',
  main_reasons: ['Skill alignment is high for software roles.'],
  strengths: ['Technical baseline and learning velocity are strong.'],
  risks_or_gaps: ['Production portfolio depth is still limited.'],
  market_context: ['Demand remains high for software engineering roles.'],
  next_actions: ['Ship one production-grade project in 30 days.'],
  confidence_explanation:
    'Confidence remains stable because scoring consistency and taxonomy mapping are both strong.',
};

function createDecisionResponse(
  explanationOverride?: DecisionResponse['explanation'],
): DecisionResponse {
  return {
    contract_version: '2026-04-02.v1',
    response_schema_version: 'one_button.response.v1',
    request_endpoint: '/api/v1/one-button/run',
    canonical_endpoint: '/api/v1/one-button/run',
    stage_manifest: [
      'taxonomy_normalize',
      'taxonomy_validate',
      'rule_engine',
      'ml_predict',
      'scoring',
      'explain',
      'diagnostics',
      'stage_trace',
    ],
    idempotency: {
      key: null,
      status: 'stored',
      replayed: false,
      request_hash: 'hash-001',
    },
    trace_id: 'trace-ui-structured-001',
    timestamp: '2026-04-09T00:00:00.000Z',
    status: 'SUCCESS',
    rankings: [
      {
        name: 'Software Engineer',
        domain: 'technology',
        total_score: 0.9,
        skill_score: 0.9,
        interest_score: 0.87,
        market_score: 0.85,
        growth_potential: 0.82,
        ai_relevance: 0.9,
      },
    ],
    top_career: {
      name: 'Software Engineer',
      domain: 'technology',
      total_score: 0.9,
      skill_score: 0.9,
      interest_score: 0.87,
      market_score: 0.85,
      growth_potential: 0.82,
      ai_relevance: 0.9,
    },
    explanation:
      explanationOverride ?? {
        summary: 'Legacy summary is still available for compatibility.',
        factors: [
          {
            name: 'skills',
            contribution: 0.32,
            description: 'Skills are strongly aligned with software engineering paths.',
          },
        ],
        confidence: 0.84,
        reasoning_chain: ['taxonomy', 'scoring', 'explanation'],
        structured_explanation: structuredBase,
      },
    market_insights: [],
    scoring_breakdown: {
      ml_score: 0.84,
      rule_score: 0.03,
      penalty: 0.01,
      final_score: 0.86,
      result_hash: 'result-hash-001',
    },
    rule_applied: [],
    reasoning_path: [],
    stage_log: [],
    diagnostics: {
      total_latency_ms: 25,
      stage_count: 8,
      stage_passed: 8,
      stage_skipped: 0,
      stage_failed: 0,
      slowest_stage: 'scoring',
      errors: [],
      llm_used: false,
      rules_audited: 0,
    },
    stage_trace: [],
    pipeline_duration_ms: 25,
    entrypoint: '/api/v1/one-button/run',
    entrypoint_enforced: true,
    meta: {
      correlation_id: 'corr-ui-001',
      pipeline_duration_ms: 25,
      model_version: 'v1',
      weights_version: 'w1',
      llm_used: false,
      stages_completed: ['taxonomy_normalize', 'scoring', 'explain'],
      rule_version: 'r1',
      taxonomy_version: 't1',
      schema_version: 'one_button.response.v1',
      schema_hash: 'schema-hash-001',
    },
    artifact_hash_chain_root: 'artifact-chain-root-001',
  };
}

let mountNode: HTMLDivElement;
let root: Root;

class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin = '0px';
  readonly thresholds = [0];

  disconnect(): void {}
  observe(_target: Element): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
  unobserve(_target: Element): void {}
}

async function click(element: HTMLElement): Promise<void> {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}

async function runOneButtonFlow(): Promise<void> {
  const startButton = mountNode.querySelector<HTMLButtonElement>(
    'button[aria-label="Bắt đầu đánh giá nghề nghiệp"]',
  );
  expect(startButton).not.toBeNull();

  await click(startButton as HTMLButtonElement);

  const submitButton = mountNode.querySelector<HTMLButtonElement>(
    'button[data-testid="mock-chatflow-submit"]',
  );
  expect(submitButton).not.toBeNull();

  await click(submitButton as HTMLButtonElement);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('OneButtonPage structured explanation UX', () => {
  beforeEach(async () => {
    runDecisionPipelineMock.mockReset();
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.IntersectionObserver = MockIntersectionObserver;
    mountNode = document.createElement('div');
    document.body.appendChild(mountNode);
    root = createRoot(mountNode);

    await act(async () => {
      root.render(<OneButtonPage />);
    });
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    delete (globalThis as Partial<typeof globalThis>).IntersectionObserver;
    mountNode.remove();
  });

  it('renders structured sections in priority order for readability', async () => {
    runDecisionPipelineMock.mockResolvedValueOnce(createDecisionResponse());

    await runOneButtonFlow();

    const sectionTitles = Array.from(mountNode.querySelectorAll('h4'))
      .map((node) => node.textContent?.trim())
      .filter((title): title is string => Boolean(title));

    expect(sectionTitles).toEqual([
      'Lý do chính',
      'Hành động đề xuất',
      'Rủi ro hoặc khoảng trống',
      'Điểm mạnh',
      'Bối cảnh thị trường',
    ]);
  });

  it('renders structured explanation even when legacy summary is empty', async () => {
    runDecisionPipelineMock.mockResolvedValueOnce(
      createDecisionResponse({
        summary: '',
        factors: [],
        confidence: 0.79,
        reasoning_chain: [],
        structured_explanation: {
          ...structuredBase,
          summary: 'Structured-only summary remains visible on the page.',
        },
      }),
    );

    await runOneButtonFlow();

    expect(mountNode.textContent).toContain('Structured-only summary remains visible on the page.');
    expect(mountNode.textContent).not.toContain('Explanation payload invalid');
  });
});
