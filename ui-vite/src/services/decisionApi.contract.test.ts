import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import contractFixtureRaw from '../../../contracts/one_button_consumer_contract_v1.json';

import {
  checkDecisionServiceHealth,
  runDecisionPipeline,
  type DecisionInput,
} from './decisionApi';

interface ContractFixture {
  canonical_endpoint: string;
  health_endpoint: string;
  contract_version: string;
  request_schema_version: string;
  response_schema_version: string;
  required_stage_manifest: string[];
  required_response_fields: string[];
  frontend_request_sample: {
    user_id: string;
    scoring_input: {
      personal_profile: {
        interests: string[];
        ability_score: number;
        confidence_score: number;
      };
      experience: {
        years: number;
        domains: string[];
      };
      goals: {
        career_aspirations: string[];
        timeline_years: number;
      };
      skills: string[];
      education: {
        level: string;
        field_of_study: string;
      };
      preferences: {
        preferred_domains: string[];
        work_style: string;
      };
    };
  };
}

const CONTRACT_FIXTURE: ContractFixture = contractFixtureRaw as ContractFixture;

const SAMPLE_INPUT: DecisionInput = {
  user_id: CONTRACT_FIXTURE.frontend_request_sample.user_id,
  profile: {
    skills: CONTRACT_FIXTURE.frontend_request_sample.scoring_input.skills,
    interests: CONTRACT_FIXTURE.frontend_request_sample.scoring_input.personal_profile.interests,
    education_level: CONTRACT_FIXTURE.frontend_request_sample.scoring_input.education.level,
    education_field_of_study:
      CONTRACT_FIXTURE.frontend_request_sample.scoring_input.education.field_of_study,
    ability_score: CONTRACT_FIXTURE.frontend_request_sample.scoring_input.personal_profile.ability_score,
    confidence_score:
      CONTRACT_FIXTURE.frontend_request_sample.scoring_input.personal_profile.confidence_score,
  },
  experience: CONTRACT_FIXTURE.frontend_request_sample.scoring_input.experience,
  goals: CONTRACT_FIXTURE.frontend_request_sample.scoring_input.goals,
  preferences: CONTRACT_FIXTURE.frontend_request_sample.scoring_input.preferences,
};

function makeSuccessResponse() {
  const stages = Object.fromEntries(
    CONTRACT_FIXTURE.required_stage_manifest.map((stage) => [
      stage,
      {
        stage,
        status: 'ok',
        duration_ms: 2,
      },
    ])
  );

  return {
    contract_version: CONTRACT_FIXTURE.contract_version,
    response_schema_version: CONTRACT_FIXTURE.response_schema_version,
    request_endpoint: CONTRACT_FIXTURE.canonical_endpoint,
    canonical_endpoint: CONTRACT_FIXTURE.canonical_endpoint,
    stage_manifest: CONTRACT_FIXTURE.required_stage_manifest,
    idempotency: {
      key: null,
      status: 'not_provided',
      replayed: false,
      request_hash: null,
    },
    trace_id: 'trace-contract-001',
    timestamp: '2026-04-02T00:00:00Z',
    status: 'SUCCESS',
    rankings: [
      {
        name: 'Software Engineer',
        domain: 'technology',
        total_score: 0.9,
        skill_score: 0.9,
        interest_score: 0.85,
        market_score: 0.88,
        growth_potential: 0.82,
        ai_relevance: 0.9,
      },
    ],
    top_career: {
      name: 'Software Engineer',
      domain: 'technology',
      total_score: 0.9,
      skill_score: 0.9,
      interest_score: 0.85,
      market_score: 0.88,
      growth_potential: 0.82,
      ai_relevance: 0.9,
    },
    explanation: {
      summary: 'Backend contract remained stable and explanation is non-empty.',
      factors: [
        {
          name: 'skills',
          contribution: 0.4,
          description: 'Python skills align with software engineering tracks.',
        },
      ],
      confidence: 0.8,
      reasoning_chain: ['taxonomy', 'scoring', 'explanation'],
      structured_explanation: {
        summary: 'Structured explanation summary from provider.',
        main_reasons: ['Skill alignment is high for the selected domain.'],
        strengths: ['Consistent technical skill signals.'],
        risks_or_gaps: ['Need stronger portfolio evidence.'],
        market_context: ['Demand remains high for this role.'],
        next_actions: ['Build one production-grade project.'],
        confidence_explanation: 'Confidence is supported by coherent scoring and taxonomy alignment.',
      },
    },
    market_insights: [],
    scoring_breakdown: {
      ml_score: 0.9,
      rule_score: 0.88,
      penalty: 0,
      final_score: 0.9,
      result_hash: 'result-hash-001',
    },
    rule_applied: [],
    reasoning_path: ['taxonomy', 'scoring', 'explanation'],
    stage_log: [],
    diagnostics: {
      total_latency_ms: 30,
      stage_count: 8,
      stage_passed: 8,
      stage_skipped: 0,
      stage_failed: 0,
      slowest_stage: 'scoring',
      errors: [],
      llm_used: false,
      rules_audited: 1,
    },
    stages,
    stage_trace: CONTRACT_FIXTURE.required_stage_manifest.map((stage) => ({
      stage,
      status: 'ok',
      duration_ms: 2,
    })),
    pipeline_duration_ms: 30,
    entrypoint: CONTRACT_FIXTURE.canonical_endpoint,
    entrypoint_enforced: true,
    meta: {
      correlation_id: 'corr-contract-001',
      pipeline_duration_ms: 30,
      model_version: 'v1',
      weights_version: 'default',
      llm_used: false,
      stages_completed: CONTRACT_FIXTURE.required_stage_manifest,
      rule_version: 'r1',
      taxonomy_version: 't1',
      schema_version: CONTRACT_FIXTURE.response_schema_version,
      schema_hash: 'schema-hash-001',
    },
    artifact_hash_chain_root: 'artifact-root-001',
  };
}

function makeFetchResponse(status: number, payload: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

describe('decisionApi consumer-driven contract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    vi.stubGlobal(
      'crypto',
      {
        randomUUID: vi.fn().mockReturnValue('00000000-0000-0000-0000-000000000001'),
      } as unknown as Crypto
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('sends canonical contract envelope and accepts required response fields', async () => {
    const fetchMock = globalThis.fetch as unknown as Mock;
    fetchMock.mockResolvedValue(makeFetchResponse(200, makeSuccessResponse()));

    const result = await runDecisionPipeline(SAMPLE_INPUT);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith(CONTRACT_FIXTURE.canonical_endpoint)).toBe(true);

    const requestBody = JSON.parse(String(init.body));
    expect(requestBody.contract_version).toBe(CONTRACT_FIXTURE.contract_version);
    expect(requestBody.request_schema_version).toBe(CONTRACT_FIXTURE.request_schema_version);

    expect(result.contract_version).toBe(CONTRACT_FIXTURE.contract_version);
    expect(result.response_schema_version).toBe(CONTRACT_FIXTURE.response_schema_version);
    expect(result.stage_manifest).toEqual(CONTRACT_FIXTURE.required_stage_manifest);

    for (const field of CONTRACT_FIXTURE.required_response_fields) {
      expect(result).toHaveProperty(field);
    }
  });

  it('accepts structured explanation even when legacy summary is empty', async () => {
    const fetchMock = globalThis.fetch as unknown as Mock;
    const payload = makeSuccessResponse();

    payload.explanation.summary = '';
    payload.explanation.factors = [];
    payload.explanation.structured_explanation = {
      summary: 'Structured-only explanation is still valid for consumers.',
      main_reasons: ['Ranking confidence is driven by domain-skill alignment.'],
      strengths: ['Strong baseline capability profile.'],
      risks_or_gaps: ['Experience depth should be expanded.'],
      market_context: ['Market demand remains favorable.'],
      next_actions: ['Complete one guided capstone project.'],
      confidence_explanation: 'Confidence remains acceptable due to cross-stage consistency.',
    };

    fetchMock.mockResolvedValue(makeFetchResponse(200, payload));

    const result = await runDecisionPipeline(SAMPLE_INPUT);

    expect(result.explanation?.summary).toContain('Structured-only explanation');
    expect(result.explanation?.structured_explanation?.main_reasons.length).toBeGreaterThan(0);
  });

  it('maps provider 400 responses to non-retryable validation errors', async () => {
    const fetchMock = globalThis.fetch as unknown as Mock;
    fetchMock.mockResolvedValue(
      makeFetchResponse(400, {
        detail: {
          error: 'ONE_BUTTON_CONTRACT_VERSION_MISMATCH',
        },
      })
    );

    await expect(runDecisionPipeline(SAMPLE_INPUT)).rejects.toMatchObject({
      code: 'VALIDATION_ERROR',
      retryable: false,
    });
  });

  it('maps provider 500 responses to retryable server errors', async () => {
    const fetchMock = globalThis.fetch as unknown as Mock;
    fetchMock.mockResolvedValue(
      makeFetchResponse(500, {
        detail: {
          error: 'ONE_BUTTON_PIPELINE_ERROR',
        },
      })
    );

    await expect(runDecisionPipeline(SAMPLE_INPUT)).rejects.toMatchObject({
      code: 'SERVER_ERROR',
      retryable: true,
    });
  });

  it('enforces timeout even when external abort signal is supplied', async () => {
    const fetchMock = globalThis.fetch as unknown as Mock;
    fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
      const requestSignal = init?.signal as AbortSignal | undefined;
      return new Promise<Response>((_resolve, reject) => {
        if (requestSignal?.aborted) {
          reject(new DOMException('The operation was aborted.', 'AbortError'));
          return;
        }
        requestSignal?.addEventListener(
          'abort',
          () => reject(new DOMException('The operation was aborted.', 'AbortError')),
          { once: true },
        );
      });
    });

    vi.useFakeTimers();
    try {
      const externalController = new AbortController();
      const pending = runDecisionPipeline(SAMPLE_INPUT, {
        signal: externalController.signal,
        timeoutMs: 25,
      });
      const assertion = expect(pending).rejects.toMatchObject({
        code: 'TIMEOUT',
        retryable: true,
      });

      await vi.advanceTimersByTimeAsync(30);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it('checks one-button health endpoint with canonical path', async () => {
    const fetchMock = globalThis.fetch as unknown as Mock;
    fetchMock.mockResolvedValue(makeFetchResponse(200, { healthy: true }));

    const healthy = await checkDecisionServiceHealth();

    expect(healthy).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith(CONTRACT_FIXTURE.health_endpoint)).toBe(true);
    expect(init.method).toBe('GET');
  });
});
