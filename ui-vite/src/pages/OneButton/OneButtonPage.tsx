// src/pages/OneButton/OneButtonPage.tsx
/**
 * One-Button Decision Page
 * ========================
 *
 * SINGLE CTA: "Bắt đầu" → POST /api/v1/one-button/run → Full result
 *
 * Architecture:
 * - NO multi-step wizard
 * - NO client-side orchestration
 * - NO partial states
 * - ONE action → ONE request → ONE response
 *
 * Deterministic scoring is the AUTHORITY.
 * LLM is used ONLY for extraction + explanation.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import {
  runDecisionPipeline,
  type DecisionResponse,
  type DecisionError,
  type DecisionInput,
  type ExplanationResult,
  type StructuredExplanation,
} from '../../services/decisionApi';
import { useTaxonomy } from '../../hooks/useTaxonomy';
import PipelineTimeline from '../../components/PipelineTimeline/PipelineTimeline';
import RuleHitHistory from '../../components/RuleHitHistory/RuleHitHistory';
import VersionTrace from '../../components/VersionTrace/VersionTrace';
import ChatFlow, { type ChatFlowData } from '../../components/features/ChatFlow/ChatFlow';
import styles from './OneButtonPage.module.css';

// ─── Đông Sơn drum — pure SVG, no deps ──────────────────────────────────────
// ─── Đông Sơn drum — faithful multi-ring SVG ───────────────────────────────
function DongSonDrumSVG({ className }: { className?: string }) {
  const cx = 250, cy = 250;
  const PI2 = Math.PI * 2;

  // ── 14-ray sun ────────────────────────────────────────────────────────────
  const rays = 14;
  const sunPath = Array.from({ length: rays }, (_, i) => {
    const a = (i / rays) * PI2 - Math.PI / 2;
    const ha = Math.PI / rays;
    const ox = cx + Math.cos(a) * 76, oy = cy + Math.sin(a) * 76;
    const l1x = cx + Math.cos(a + ha) * 28, l1y = cy + Math.sin(a + ha) * 28;
    const l2x = cx + Math.cos(a - ha) * 28, l2y = cy + Math.sin(a - ha) * 28;
    return `M${cx},${cy} L${ox},${oy} L${l1x},${l1y} Z M${cx},${cy} L${ox},${oy} L${l2x},${l2y} Z`;
  }).join(' ');

  // ── Sawtooth outer border ─────────────────────────────────────────────────
  const sawTeeth = 72;
  const sawOuter = 240, sawMid = 232, sawInner = 224;
  const sawPath = Array.from({ length: sawTeeth }, (_, i) => {
    const a1 = (i / sawTeeth) * PI2;
    const a2 = ((i + 0.5) / sawTeeth) * PI2;
    const a3 = ((i + 1) / sawTeeth) * PI2;
    return (
      `M${cx + Math.cos(a1) * sawInner},${cy + Math.sin(a1) * sawInner}` +
      ` L${cx + Math.cos(a2) * sawOuter},${cy + Math.sin(a2) * sawOuter}` +
      ` L${cx + Math.cos(a3) * sawInner},${cy + Math.sin(a3) * sawInner}`
    );
  }).join(' ');

  // ── Stylised birds (outer ring, r=210) ───────────────────────────────────
  const birdCount = 12;
  const birdRing = 210;
  const birds = Array.from({ length: birdCount }, (_, i) => {
    const a = (i / birdCount) * PI2 - Math.PI / 2;
    const bx = cx + Math.cos(a) * birdRing;
    const by = cy + Math.sin(a) * birdRing;
    const rot = (a * 180) / Math.PI + 90;
    return (
      <g key={`b${i}`} transform={`translate(${bx},${by}) rotate(${rot})`}>
        {/* body */}
        <ellipse cx={0} cy={0} rx={10} ry={5} fill="currentColor" opacity={0.9} />
        {/* head */}
        <circle cx={11} cy={-2} r={4} fill="currentColor" opacity={0.9} />
        {/* beak */}
        <line x1={14} y1={-3} x2={18} y2={-5} stroke="currentColor" strokeWidth={1.2} />
        {/* tail feather */}
        <line x1={-9} y1={0} x2={-16} y2={-6} stroke="currentColor" strokeWidth={1.5} />
        <line x1={-9} y1={0} x2={-17} y2={0} stroke="currentColor" strokeWidth={1.2} />
        {/* wing */}
        <path d={`M-2,-4 Q2,-10 8,-6`} fill="none" stroke="currentColor" strokeWidth={1.2} />
        {/* legs */}
        <line x1={2} y1={4} x2={1} y2={10} stroke="currentColor" strokeWidth={1} />
        <line x1={5} y1={4} x2={6} y2={10} stroke="currentColor" strokeWidth={1} />
      </g>
    );
  });

  // ── Inner bird ring (r=175) ───────────────────────────────────────────────
  const iBirdCount = 16;
  const iBirdRing = 175;
  const innerBirds = Array.from({ length: iBirdCount }, (_, i) => {
    const a = (i / iBirdCount) * PI2 - Math.PI / 2;
    const bx = cx + Math.cos(a) * iBirdRing;
    const by = cy + Math.sin(a) * iBirdRing;
    const rot = (a * 180) / Math.PI + 90;
    return (
      <g key={`ib${i}`} transform={`translate(${bx},${by}) rotate(${rot})`}>
        <ellipse cx={0} cy={0} rx={7} ry={3.5} fill="currentColor" opacity={0.85} />
        <circle cx={8} cy={-1.5} r={3} fill="currentColor" opacity={0.85} />
        <line x1={10} y1={-2} x2={13} y2={-4} stroke="currentColor" strokeWidth={1} />
        <line x1={-7} y1={0} x2={-12} y2={-4} stroke="currentColor" strokeWidth={1.2} />
        <line x1={2} y1={3} x2={1} y2={7} stroke="currentColor" strokeWidth={0.9} />
        <line x1={4} y1={3} x2={5} y2={7} stroke="currentColor" strokeWidth={0.9} />
      </g>
    );
  });

  // ── Deer-like animals (r=147) ─────────────────────────────────────────────
  const deerCount = 10;
  const deerRing = 147;
  const deer = Array.from({ length: deerCount }, (_, i) => {
    const a = (i / deerCount) * PI2 - Math.PI / 2;
    const dx = cx + Math.cos(a) * deerRing;
    const dy = cy + Math.sin(a) * deerRing;
    const rot = (a * 180) / Math.PI + 90;
    return (
      <g key={`d${i}`} transform={`translate(${dx},${dy}) rotate(${rot})`}>
        {/* torso */}
        <ellipse cx={0} cy={0} rx={9} ry={4.5} fill="currentColor" opacity={0.88} />
        {/* head/neck */}
        <line x1={8} y1={-2} x2={14} y2={-7} stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
        {/* head */}
        <circle cx={14.5} cy={-8} r={3} fill="currentColor" opacity={0.88} />
        {/* antler */}
        <line x1={15} y1={-10} x2={14} y2={-15} stroke="currentColor" strokeWidth={1.2} />
        <line x1={14} y1={-13} x2={17} y2={-16} stroke="currentColor" strokeWidth={1} />
        <line x1={14} y1={-13} x2={11} y2={-16} stroke="currentColor" strokeWidth={1} />
        {/* tail */}
        <line x1={-9} y1={-2} x2={-13} y2={-5} stroke="currentColor" strokeWidth={1.2} />
        {/* legs */}
        <line x1={-4} y1={4} x2={-5} y2={10} stroke="currentColor" strokeWidth={1.3} />
        <line x1={-1} y1={4} x2={-1} y2={10} stroke="currentColor" strokeWidth={1.3} />
        <line x1={3} y1={4} x2={4} y2={10} stroke="currentColor" strokeWidth={1.3} />
        <line x1={6} y1={4} x2={7} y2={10} stroke="currentColor" strokeWidth={1.3} />
      </g>
    );
  });

  // ── Ceremony figures (r=122) ──────────────────────────────────────────────
  const figCount = 8;
  const figRing = 122;
  const figures = Array.from({ length: figCount }, (_, i) => {
    const a = (i / figCount) * PI2 - Math.PI / 2;
    const fx = cx + Math.cos(a) * figRing;
    const fy = cy + Math.sin(a) * figRing;
    const rot = (a * 180) / Math.PI + 90;
    return (
      <g key={`f${i}`} transform={`translate(${fx},${fy}) rotate(${rot})`}>
        {/* head */}
        <circle cx={0} cy={-11} r={3.5} fill="currentColor" opacity={0.9} />
        {/* headdress */}
        <path d={`M-3,-14 L0,-20 L3,-14`} fill="currentColor" opacity={0.9} />
        {/* body */}
        <rect x={-3} y={-7} width={6} height={8} rx={1} fill="currentColor" opacity={0.9} />
        {/* arms */}
        <line x1={-3} y1={-4} x2={-9} y2={-7} stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" />
        <line x1={3} y1={-4} x2={9} y2={-7} stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" />
        {/* drum (every other figure holds a drum) */}
        {i % 2 === 0 && (
          <ellipse cx={10} cy={-7} rx={3} ry={2} fill="currentColor" opacity={0.75} />
        )}
        {/* legs */}
        <line x1={-2} y1={1} x2={-3} y2={8} stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" />
        <line x1={2} y1={1} x2={3} y2={8} stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" />
      </g>
    );
  });

  // ── Dense tick marks for separator rings ─────────────────────────────────
  function TickRing({ r, count, h }: { r: number; count: number; h: number }) {
    return (
      <>
        {Array.from({ length: count }, (_, i) => {
          const a = (i / count) * PI2;
          return (
            <line
              key={i}
              x1={cx + Math.cos(a) * r}
              y1={cy + Math.sin(a) * r}
              x2={cx + Math.cos(a) * (r + h)}
              y2={cy + Math.sin(a) * (r + h)}
              stroke="currentColor"
              strokeWidth={1}
            />
          );
        })}
      </>
    );
  }

  // ── Diamond/lozenge band (r=100) ─────────────────────────────────────────
  const diamondCount = 20;
  const dRing = 100;
  const diamonds = Array.from({ length: diamondCount }, (_, i) => {
    const a = (i / diamondCount) * PI2;
    const dx = cx + Math.cos(a) * dRing;
    const dy = cy + Math.sin(a) * dRing;
    const rot = (a * 180) / Math.PI;
    return (
      <g key={`dm${i}`} transform={`translate(${dx},${dy}) rotate(${rot})`}>
        <polygon points="0,-5 3.5,0 0,5 -3.5,0" fill="currentColor" opacity={0.7} />
      </g>
    );
  });

  return (
    <svg
      className={className}
      viewBox="0 0 500 500"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* ── Outer sawtooth border ── */}
      <path d={sawPath} fill="currentColor" opacity={0.6} />
      <circle cx={cx} cy={cy} r={sawMid} fill="none" stroke="currentColor" strokeWidth={0.8} />
      <circle cx={cx} cy={cy} r={sawInner} fill="none" stroke="currentColor" strokeWidth={1.2} />

      {/* ── Outer separator ring ── */}
      <circle cx={cx} cy={cy} r={222} fill="none" stroke="currentColor" strokeWidth={0.6} />
      <TickRing r={218} count={60} h={4} />
      <circle cx={cx} cy={cy} r={216} fill="none" stroke="currentColor" strokeWidth={0.6} />

      {/* ── Outer birds ring ── */}
      <circle cx={cx} cy={cy} r={196} fill="none" stroke="currentColor" strokeWidth={1} />
      {birds}
      <circle cx={cx} cy={cy} r={191} fill="none" stroke="currentColor" strokeWidth={0.7} />
      <TickRing r={188} count={48} h={3} />
      <circle cx={cx} cy={cy} r={185} fill="none" stroke="currentColor" strokeWidth={1} />

      {/* ── Inner birds ring ── */}
      {innerBirds}
      <circle cx={cx} cy={cy} r={160} fill="none" stroke="currentColor" strokeWidth={1} />
      <TickRing r={157} count={48} h={3} />
      <circle cx={cx} cy={cy} r={154} fill="none" stroke="currentColor" strokeWidth={0.7} />

      {/* ── Deer ring ── */}
      {deer}
      <circle cx={cx} cy={cy} r={132} fill="none" stroke="currentColor" strokeWidth={1.2} />
      <TickRing r={129} count={40} h={3} />
      <circle cx={cx} cy={cy} r={126} fill="none" stroke="currentColor" strokeWidth={0.7} />

      {/* ── Ceremony figures ring ── */}
      {figures}
      <circle cx={cx} cy={cy} r={108} fill="none" stroke="currentColor" strokeWidth={1} />

      {/* ── Diamond geometric band ── */}
      {diamonds}
      <circle cx={cx} cy={cy} r={90} fill="none" stroke="currentColor" strokeWidth={1} />
      <TickRing r={87} count={32} h={3} />
      <circle cx={cx} cy={cy} r={84} fill="none" stroke="currentColor" strokeWidth={0.8} />

      {/* ── Inner concentric rings ── */}
      <circle cx={cx} cy={cy} r={78} fill="none" stroke="currentColor" strokeWidth={1} />
      <circle cx={cx} cy={cy} r={72} fill="none" stroke="currentColor" strokeWidth={0.7} />

      {/* ── 14-ray sun ── */}
      <path d={sunPath} fill="currentColor" opacity={0.8} />

      {/* ── Centre dot ── */}
      <circle cx={cx} cy={cy} r={18} fill="none" stroke="currentColor" strokeWidth={1.5} />
      <circle cx={cx} cy={cy} r={7} fill="currentColor" opacity={0.6} />
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════
// FLOW ARROW — SVG dashed animated connector
// ═══════════════════════════════════════════════════════════════════

type ArrowDir = 'down-right' | 'down-left' | 'down';

function FlowArrow({ dir = 'down' }: { dir?: ArrowDir }) {
  const paths: Record<ArrowDir, string> = {
    'down-right': 'M 40,8 Q 120,8 120,40 L 120,66',
    'down-left':  'M 200,8 Q 120,8 120,40 L 120,66',
    'down':       'M 120,5 L 120,66',
  };
  return (
    <div className={styles.flowArrowWrap} aria-hidden="true">
      <svg
        viewBox="0 0 240 76"
        className={styles.flowArrowSvg}
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d={paths[dir]}
          fill="none"
          stroke="rgba(212,162,76,0.35)"
          strokeWidth="1.5"
          strokeDasharray="6 4"
          strokeLinecap="round"
          className={styles.flowArrowPath}
        />
        {/* Arrowhead */}
        <polygon points="115,62 120,74 125,62" fill="rgba(212,162,76,0.5)" />
      </svg>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// STATE TYPES
// ═══════════════════════════════════════════════════════════════════

type PipelineState = 'idle' | 'executing' | 'success' | 'error';

interface PipelineResult {
  response: DecisionResponse | null;
  error: DecisionError | null;
}

// ── Type guard: rejects null, {}, and objects with missing/short summary ─────
function cleanStructuredList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter((item) => item.length > 0)
    .slice(0, 5);
}

function normalizeStructuredExplanation(
  raw: unknown,
  fallbackSummary: string,
): StructuredExplanation | null {
  if (!raw || typeof raw !== 'object') {
    return null;
  }

  const structured = raw as Record<string, unknown>;
  const summary =
    typeof structured.summary === 'string' && structured.summary.trim().length >= 10
      ? structured.summary.trim()
      : fallbackSummary.trim();

  const confidenceExplanation =
    typeof structured.confidence_explanation === 'string' &&
    structured.confidence_explanation.trim().length > 0
      ? structured.confidence_explanation.trim()
      : 'Độ tin cậy phản ánh mức nhất quán giữa hồ sơ hiện tại và tín hiệu chấm điểm.';

  if (summary.length < 10) {
    return null;
  }

  return {
    summary,
    main_reasons: cleanStructuredList(structured.main_reasons),
    strengths: cleanStructuredList(structured.strengths),
    risks_or_gaps: cleanStructuredList(structured.risks_or_gaps),
    market_context: cleanStructuredList(structured.market_context),
    next_actions: cleanStructuredList(structured.next_actions),
    confidence_explanation: confidenceExplanation,
  };
}

function buildStructuredSections(
  structured: StructuredExplanation | null,
): Array<{ title: string; items: string[] }> {
  if (!structured) {
    return [];
  }

  // Priority is tuned for actionability: reason -> action -> risk -> strengths -> market.
  const prioritizedSections = [
    { title: 'Lý do chính', items: structured.main_reasons, priority: 100 },
    { title: 'Hành động đề xuất', items: structured.next_actions, priority: 90 },
    { title: 'Rủi ro hoặc khoảng trống', items: structured.risks_or_gaps, priority: 80 },
    { title: 'Điểm mạnh', items: structured.strengths, priority: 70 },
    { title: 'Bối cảnh thị trường', items: structured.market_context, priority: 60 },
  ];

  return prioritizedSections
    .filter((section) => section.items.length > 0)
    .sort((a, b) => b.priority - a.priority)
    .map(({ title, items }) => ({ title, items }));
}

function isValidExplanation(e: unknown): e is ExplanationResult {
  if (!e || typeof e !== 'object') return false;
  const ex = e as ExplanationResult;
  const hasLegacy =
    typeof ex.summary === 'string' &&
    ex.summary.trim().length >= 10 &&
    Array.isArray(ex.factors) &&
    typeof ex.confidence === 'number';

  const hasStructured = normalizeStructuredExplanation(ex.structured_explanation, ex.summary) !== null;
  return hasLegacy || hasStructured;
}

// ═══════════════════════════════════════════════════════════════════
// DEFAULT INPUT (can be customized via simple form)
// ═══════════════════════════════════════════════════════════════════

const DEFAULT_INPUT: DecisionInput = {
  profile: {
    skills: [],
    interests: [],
    education_level: '',
    // skills, interests and education_level are populated dynamically from the taxonomy API
    ability_score: 0.7,
    confidence_score: 0.6,
  },
  features: {
    math_score: 7.5,
    logic_score: 8.0,
    physics_score: 7.0,
    creativity_score: 6.5,
    interest_tech: 8.5,
    interest_science: 7.0,
  },
};

// ═══════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════

export default function OneButtonPage() {
  const [state, setState] = useState<PipelineState>('idle');
  const [result, setResult] = useState<PipelineResult>({ response: null, error: null });
  const [showInputForm, setShowInputForm] = useState(false);
  const [input, setInput] = useState<DecisionInput>(DEFAULT_INPUT);
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [showChatFlow, setShowChatFlow] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);
  const lastPayloadRef = useRef<DecisionInput>(DEFAULT_INPUT);
  // Bound to trace_id — forces key-prop remount of explanation card on every new response
  const [explainKey, setExplainKey] = useState<string>('');

  // ── Dynamic taxonomy from API — no hardcoded values ──────────────────────
  const { skills: skillOptions, interests: interestOptions, education: educationOptions, loading: taxonomyLoading } = useTaxonomy();

  // Seed default education once taxonomy is loaded
  useEffect(() => {
    if (!taxonomyLoading && educationOptions.length > 0 && input.profile.education_level === '') {
      const bachelor = educationOptions.find(e => e.id === 'bachelor');
      setInput(prev => ({
        ...prev,
        profile: { ...prev.profile, education_level: bachelor ? bachelor.label : educationOptions[0].label },
      }));
    }
  }, [taxonomyLoading, educationOptions]);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []);

  // ── Scroll reveal via IntersectionObserver ──────────────────────
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>('[data-reveal]');
    if (!els.length) return;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).dataset.reveal = 'visible';
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    els.forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  });

  // ═══════════════════════════════════════════════════════════════════
  // MAIN ACTION - ONE BUTTON
  // ═══════════════════════════════════════════════════════════════════
  
  // ── Core pipeline runner — accepts explicit payload, no implicit state ───
  const handleStartWithPayload = useCallback(async (payload: DecisionInput) => {
    if (state === 'executing') return;

    // Cancel any in-flight request before starting a new one
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    lastPayloadRef.current = payload;
    setState('executing');
    // Clear previous result immediately so stale explanation cannot bleed through
    setResult({ response: null, error: null });
    setExplainKey('');

    try {
      const response = await runDecisionPipeline(payload, {
        signal: controller.signal,
        timeoutMs: 20000,
      });

      // If this controller was superseded by a later submit, discard silently
      if (controller.signal.aborted) return;

      // Bind explainKey to trace_id — forces key-prop remount on every new response
      setExplainKey(response.trace_id);
      setState('success');
      setResult({ response, error: null });
    } catch (error) {
      if (controller.signal.aborted) return;
      setState('error');
      setResult({
        response: null,
        error: error as DecisionError,
      });
    }
  }, [state]);

  // ── Assemble payload from 6-step chat data, then run pipeline ────────────
  const handleChatFlowComplete = useCallback((data: ChatFlowData) => {
    setShowChatFlow(false);

    // ════════════════════════════════════════════════════════════════════════
    // CANONICALIZATION — convert every raw string answer to a typed value
    // ════════════════════════════════════════════════════════════════════════

    // ─── Step 1 fields ───────────────────────────────────────────────────────
    const ageRaw   = parseInt((data.profile_raw.age ?? '').replace(/[^\d]/g, ''), 10);
    const age      = isNaN(ageRaw) ? 0 : Math.min(Math.max(ageRaw, 1), 120);

    const location = (data.profile_raw.location ?? '').trim();

    const mobilityRaw = (data.profile_raw.mobility ?? '').toLowerCase();
    const mobility    = mobilityRaw.includes('có') || mobilityRaw === 'yes' || mobilityRaw.startsWith('y');

    const languages = (data.profile_raw.languages ?? '')
      .split(/[,;/]/)
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);

    // ─── Step 2 fields ───────────────────────────────────────────────────────
    const rawSkills = (data.skills_input.skills_list ?? '');
    const skills    = rawSkills
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);

    const yearsUsedRaw = parseInt((data.skills_input.years_used ?? '').replace(/[^\d]/g, ''), 10);
    const yearsUsed    = isNaN(yearsUsedRaw) ? 0 : Math.min(yearsUsedRaw, 50);

    const realWorldRaw    = (data.skills_input.real_world_used ?? '').toLowerCase();
    const realWorldUsed   = realWorldRaw.includes('có') || realWorldRaw === 'yes' || realWorldRaw.startsWith('y');

    const certifiedRaw = (data.skills_input.certified ?? '').toLowerCase();
    const certified    = certifiedRaw.includes('có') || certifiedRaw === 'yes' || certifiedRaw.startsWith('y');

    // Skill level → 0-1 numeric (Cơ bản=0.3 | Trung bình=0.6 | Nâng cao=0.9)
    const skillLevelRaw   = (data.skills_input.skill_levels ?? '').toLowerCase();
    const skillLevelScore =
      skillLevelRaw.includes('nâng cao') || skillLevelRaw.includes('advanced')
        ? 0.9
        : skillLevelRaw.includes('') || skillLevelRaw.includes('intermediate')
        ? 0.6
        : 0.3; // basic default

    // ─── Step 3 fields ───────────────────────────────────────────────────────
    const preferredIndustry = (data.interest_raw.preferred_industry ?? '')
      .split(/[,;]/)
      .map((s) => s.trim().toLowerCase())
      .filter((s) => s && s !== 'không');

    const excludedIndustry = (data.interest_raw.excluded_industry ?? '')
      .split(/[,;]/)
      .map((s) => s.trim().toLowerCase())
      .filter((s) => s && s !== 'không');

    const workStyleRaw = (data.interest_raw.work_style ?? '').toLowerCase();
    const workStyle: 'team' | 'independent' | 'mixed' = workStyleRaw.includes('nhóm')
      ? 'team'
      : workStyleRaw.includes('độc lập')
      ? 'independent'
      : 'mixed';

    // ─── Step 4 fields ───────────────────────────────────────────────────────
    const degreeRaw = (data.education_input.degree_level ?? '').toLowerCase().trim();
    const eduMap: [string, string][] = [
      ['tiến sĩ', 'PhD'],
      ['thạc sĩ', 'Master'],
      ['đại học', 'Bachelor'],
      ['cao đẳng', 'Associate'],
      ['thpt', 'High School'],
    ];
    const education_level = eduMap.find(([k]) => degreeRaw.includes(k))?.[1] ?? 'Bachelor';

    // expected_salary — extract first numeric sequence, treat as VND million/month
    const salaryStr    = (data.education_input.expected_salary ?? '');
    const salaryMatch  = salaryStr.match(/(\d+[\.,]?\d*)/);
    const expectedSalary = salaryMatch ? parseFloat(salaryMatch[1].replace(',', '.')) : 0;

    // priority_weight → enum
    const pwRaw = (data.education_input.priority_weight ?? '').toLowerCase();
    const priorityWeight =
      pwRaw.includes('thu nhập')     ? 'income'
      : pwRaw.includes('sáng tạo')  ? 'creativity'
      : pwRaw.includes('xã hội') || pwRaw.includes('ảnh hưởng') ? 'social_impact'
      : 'stability';

    const trainingRaw            = parseInt((data.education_input.training_horizon_months ?? '').replace(/[^\d]/g, ''), 10);
    const trainingHorizonMonths  = isNaN(trainingRaw) ? 0 : Math.min(trainingRaw, 120);

    // ─── Step 5 fields ───────────────────────────────────────────────────────
    const yearsExpRaw    = parseInt((data.experience_data.years ?? '').replace(/[^\d]/g, ''), 10);
    const yearsExperience = isNaN(yearsExpRaw) ? 0 : Math.min(yearsExpRaw, 50);

    // Use the greater of step-2 years_used and step-5 years as the effective experience
    const effectiveYears = Math.max(yearsUsed, yearsExperience);

    // ─── Step 6 fields ───────────────────────────────────────────────────────
    const explanationDepth = (data.goal_raw.explanation_depth ?? '').toLowerCase().includes('chi tiết')
      ? 'detailed'
      : 'summary';

    const roadmapHorizon = (data.goal_raw.roadmap_horizon ?? '').toLowerCase().includes('3')
      ? '3years'
      : '6months';

    const consentRaw    = (data.goal_raw.consent_flag ?? '').toLowerCase();
    const consentFlag   = consentRaw.includes('có') || consentRaw === 'yes' || consentRaw.startsWith('y');

    const saveProfileRaw = (data.goal_raw.save_profile ?? '').toLowerCase();
    const saveProfile    = saveProfileRaw.includes('có') || saveProfileRaw === 'yes' || saveProfileRaw.startsWith('y');

    // ════════════════════════════════════════════════════════════════════════
    // PRE-FLIGHT VALIDATION — block API call on bad data
    // ════════════════════════════════════════════════════════════════════════
    const validationErrors: string[] = [];

    if (!age || age < 10 || age > 100) {
      validationErrors.push('Tuổi không hợp lệ — vui lòng nhập số nguyên từ 10 đến 100 (ví dụ: 22)');
    }
    if (skills.length === 0) {
      validationErrors.push('Danh sách kỹ năng không được để trống');
    }
    if (yearsExperience < 0 || yearsUsed < 0) {
      validationErrors.push('Số năm kinh nghiệm không hợp lệ — phải ≥ 0');
    }
    if (!education_level || education_level.trim() === '') {
      validationErrors.push('Trình độ học vấn là bắt buộc (THPT / Cao đẳng / Đại học / Thạc sĩ / Tiến sĩ)');
    }
    if (expectedSalary < 0) {
      validationErrors.push('Mức lương kỳ vọng không hợp lệ — phải ≥ 0');
    }
    if (trainingHorizonMonths < 0) {
      validationErrors.push('Thời gian đào tạo không hợp lệ');
    }
    // consent_flag must have been answered (non-empty raw answer)
    if (!(data.goal_raw.consent_flag ?? '').trim()) {
      validationErrors.push('Vui lòng trả lời câu hỏi đồng ý chia sẻ dữ liệu (Bước 6)');
    }

    if (validationErrors.length > 0) {
      setState('error');
      setResult({
        response: null,
        error: {
          code: 'VALIDATION_ERROR',
          message: 'D\u1eef li\u1ec7u nh\u1eadp ch\u01b0a \u0111\u1ea7y \u0111\u1ee7 ho\u1eb7c kh\u00f4ng h\u1ee3p l\u1ec7: ' + validationErrors.join(' | '),
          retryable: false,
        },
      });
      return;
    }

    // ════════════════════════════════════════════════════════════════════════
    // PAYLOAD ASSEMBLY — map canonicalized values → DecisionInput
    // ════════════════════════════════════════════════════════════════════════

    // Collect interests from all semantic sources
    const interestSources = [
      data.interest_raw.work_preference,
      data.interest_raw.environment,
      data.interest_raw.motivation,
      data.goal_raw.priority,
      data.profile_raw.current_field,
      ...preferredIndustry,
    ];
    const interests = interestSources
      .filter(Boolean)
      .map((s) => s!.trim().toLowerCase());

    // ability_score: base 0.45 + experience + certification bonuses
    let ability_score = Math.min(0.45 + Math.min(effectiveYears, 15) * 0.04, 0.90);
    if (certified)      ability_score = Math.min(ability_score + 0.05, 0.95);
    if (realWorldUsed)  ability_score = Math.min(ability_score + 0.02, 0.95);
    if (skillLevelScore >= 0.9) ability_score = Math.min(ability_score + 0.03, 0.95);

    // confidence_score: driven by priority preference
    const confidence_score =
      priorityWeight === 'income'        ? 0.70
      : priorityWeight === 'creativity'  ? 0.72
      : priorityWeight === 'social_impact' ? 0.68
      : 0.65; // stability

    // Feature score computation
    const pref    = (data.interest_raw.work_preference ?? '').toLowerCase();
    const env     = (data.interest_raw.environment ?? '').toLowerCase();
    const pri     = (data.goal_raw.priority ?? '').toLowerCase();

    // Boost modifiers from new canonicalized fields
    const trainingBoost  = trainingHorizonMonths > 12 ? 0.5 : trainingHorizonMonths > 6 ? 0.3 : 0.0;
    const mobilityBoost  = mobility ? 0.4 : 0.0;
    const multiLangBoost = languages.length > 1 ? 0.3 : 0.0;
    const teamBoost      = workStyle === 'team' ? 0.8 : 0.0;
    const soloBoost      = workStyle === 'independent' ? 0.8 : 0.0;
    const creativeBoost  = priorityWeight === 'creativity' ? 1.2 : 0.0;
    const socialBoost    = priorityWeight === 'social_impact' ? 1.2 : 0.0;

    // Base interest scores from work_preference
    const baseTech    = pref.includes('h\u1ec7 th\u1ed1ng') || pref.includes('c\u00f4ng ngh\u1ec7') ? 8.5 : 4.5;
    const baseScience = pref.includes('d\u1eef li\u1ec7u') ? 8.0 : 4.5;
    const baseSocial  = pref.includes('con ng\u01b0\u1eddi') ? 8.0 : 4.0;
    const baseArts    = env.includes('s\u00e1ng t\u1ea1o') || env.includes('n\u0103ng \u0111\u1ed9ng') ? 7.0 : 4.0;

    const rawFeatures: Record<string, number> = {
      interest_tech:    baseTech    + trainingBoost + mobilityBoost * 0.5,
      interest_science: baseScience + trainingBoost * 0.5 + multiLangBoost * 0.3,
      interest_social:  baseSocial  + teamBoost + socialBoost,
      interest_arts:    baseArts    + creativeBoost,
      creativity_score: (env.includes('n\u0103ng \u0111\u1ed9ng') || env.includes('s\u00e1ng t\u1ea1o') ? 7.5 : 5.0) + creativeBoost,
      logic_score:      (pref.includes('d\u1eef li\u1ec7u') || pref.includes('h\u1ec7 th\u1ed1ng') ? 7.5 : 5.5) + soloBoost + multiLangBoost,
      math_score:       (pref.includes('d\u1eef li\u1ec7u') ? 7.0 : 5.5) + multiLangBoost * 0.5,
    };

    // Clamp all feature scores to valid range [1 .. 10]
    const features: DecisionInput['features'] = {};
    for (const [k, v] of Object.entries(rawFeatures)) {
      (features as Record<string, number>)[k] = Math.max(1, Math.min(10, v));
    }

    // ── Derived domains: preferredIndustry → top skills as fallback ───────────
    const domainList: string[] =
      preferredIndustry.length > 0
        ? preferredIndustry
        : skills.slice(0, 3).length > 0
        ? skills.slice(0, 3)
        : ['general'];

    // ── career_aspirations: target_position + priority context ────────────
    const careerAspirations: string[] = [];
    const targetPosition = (data.goal_raw.target_position ?? '').trim().toLowerCase();
    if (targetPosition) careerAspirations.push(targetPosition);
    if (priorityWeight === 'income')        careerAspirations.push('high-income professional');
    else if (priorityWeight === 'creativity')   careerAspirations.push('creative professional');
    else if (priorityWeight === 'social_impact') careerAspirations.push('social impact career');
    else                                         careerAspirations.push('stable professional career');

    // ── timeline_years from roadmapHorizon ──────────────────────────────
    const timelineYears = roadmapHorizon === '3years' ? 3 : 1;

    // ── education.field_of_study from Step 4 ───────────────────────────
    const fieldOfStudy = (data.education_input.field_of_study ?? '').trim() || 'general';

    // Suppress fields not in current ScoringInput schema
    void location;
    void excludedIndustry;
    void explanationDepth;
    void consentFlag;
    void saveProfile;
    void expectedSalary;
    void pri;

    const payload: DecisionInput = {
      profile: {
        skills:                   skills.length > 0 ? skills : ['general'],
        interests:                interests.length > 0 ? interests : domainList,
        education_level,
        education_field_of_study: fieldOfStudy,
        ability_score,
        confidence_score,
      },
      experience: {
        years:   effectiveYears,
        domains: domainList,
      },
      goals: {
        career_aspirations: careerAspirations,
        timeline_years:     timelineYears,
      },
      preferences: {
        preferred_domains: domainList,
        work_style:        workStyle,
      },
      features,
    };

    // ════════════════════════════════════════════════════════════════════════
    // STRICT-MODE PRE-CALL ASSERTIONS
    // Mirror backend min_length constraints before fetch is ever invoked.
    // Any violation here indicates a logic error in the assembly above.
    // ════════════════════════════════════════════════════════════════════════
    const assertionErrors: string[] = [];

    if (!payload.goals?.career_aspirations || payload.goals.career_aspirations.filter(Boolean).length < 1) {
      assertionErrors.push('goals.career_aspirations phải có ít nhất 1 phần tử');
    }
    if (!payload.preferences?.preferred_domains || payload.preferences.preferred_domains.filter(Boolean).length < 1) {
      assertionErrors.push('preferences.preferred_domains phải có ít nhất 1 phần tử');
    }
    if (!payload.experience?.domains || payload.experience.domains.filter(Boolean).length < 1) {
      assertionErrors.push('experience.domains phải có ít nhất 1 phần tử');
    }
    if (!payload.profile.education_level || payload.profile.education_level.trim() === '') {
      assertionErrors.push('education.level không được là chuỗi rỗng');
    }
    if (!payload.profile.education_field_of_study || payload.profile.education_field_of_study.trim() === '') {
      assertionErrors.push('education.field_of_study không được là chuỗi rỗng');
    }
    if (!payload.preferences?.work_style || payload.preferences.work_style.trim() === '') {
      assertionErrors.push('preferences.work_style không được là chuỗi rỗng');
    }

    if (assertionErrors.length > 0) {
      setState('error');
      setResult({
        response: null,
        error: {
          code: 'VALIDATION_ERROR',
          message: 'Lỗi cấu trúc dữ liệu trước khi gọi API: ' + assertionErrors.join(' | '),
          retryable: false,
        },
      });
      return;
    }

    handleStartWithPayload(payload);
  }, [handleStartWithPayload]);

  // ═══════════════════════════════════════════════════════════════════
  // RESET
  // ═══════════════════════════════════════════════════════════════════
  
  const handleReset = useCallback(() => {
    abortControllerRef.current?.abort();
    setState('idle');
    setResult({ response: null, error: null });
    setShowChatFlow(false);
  }, []);

  // ═══════════════════════════════════════════════════════════════════
  // INPUT FORM HANDLERS
  // ═══════════════════════════════════════════════════════════════════

  const handleSkillsChange = (value: string) => {
    setInput(prev => ({
      ...prev,
      profile: {
        ...prev.profile,
        skills: value.split(',').map(s => s.trim()).filter(Boolean),
      },
    }));
  };

  const handleInterestsChange = (value: string) => {
    setInput(prev => ({
      ...prev,
      profile: {
        ...prev.profile,
        interests: value.split(',').map(s => s.trim()).filter(Boolean),
      },
    }));
  };

  const handleEducationChange = (value: string) => {
    setInput(prev => ({
      ...prev,
      profile: {
        ...prev.profile,
        education_level: value,
      },
    }));
  };

  // ═══════════════════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════════════════

  return (
    <div className={styles.page}>
      {/* ── Scattered drums — fixed behind all content throughout the page ── */}
      <div className={styles.drumField} aria-hidden="true">
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds1} ${styles.drumSpinSlow}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds2} ${styles.drumSpinMedium}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds3} ${styles.drumSpinReverse}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds4} ${styles.drumSpinSlow}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds5} ${styles.drumSpinRevMed}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds6} ${styles.drumSpinMedium}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds7} ${styles.drumSpinFast}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds8} ${styles.drumSpinReverse}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds9} ${styles.drumSpinRevMed}`} />
        <DongSonDrumSVG className={`${styles.drumScatterWrap} ${styles.ds10} ${styles.drumSpinSlow}`} />
      </div>

      {/* Subtle dot particle layer */}
      <div className={styles.particleLayer} aria-hidden="true" />

      {/* Ambient radial glow */}
      <div className={styles.glowOrb} aria-hidden="true" />

      {/* Đông Sơn drum — hero, rotating slowly */}
      <DongSonDrumSVG className={`${styles.drumSvg} ${styles.drumRotateSlow}`} />

      {/* ── idle / error ──────────────────────────────────────────── */}
      {(state === 'idle' || state === 'error') && (
        <>
          {/* ── HERO ──────────────────────────────────────────── */}
          <section className={styles.heroSection}>
            <div className={styles.stage}>
              <p className={styles.eyebrow}>Hệ thống Hỗ trợ Quyết định</p>

              <h1 className={styles.headline}>
                Khám phá nghề nghiệp
                <br />
                <span className={styles.accent}>phù hợp với bạn</span>
              </h1>

              <p className={styles.subline}>
                Phân tích toàn diện dựa trên hệ thống điểm số xác định,
                kết hợp dữ liệu thị trường lao động thực tế.
              </p>

              {state === 'error' && result.error && (
                <div className={styles.errorBanner}>
                  <span className={styles.errorDot} />
                  {result.error.message}
                </div>
              )}

              {/* ── THE ONE BUTTON ──────────────────────────────────── */}
              <button
                className={styles.ctaBtn}
                onClick={
                  state === 'error'
                    ? () => handleStartWithPayload(lastPayloadRef.current)
                    : () => setShowChatFlow(true)
                }
                aria-label="Bắt đầu đánh giá nghề nghiệp"
              >
                <span className={styles.ctaBtnInner}>
                  <span className={styles.ctaBtnRing} />
                  {state === 'error' ? 'Thử lại' : 'Bắt đầu đánh giá'}
                </span>
              </button>

              {/* In error state: secondary action to restart ChatFlow */}
              {state === 'error' && (
                <button
                  className={styles.restartLink}
                  onClick={() => {
                    setResult({ response: null, error: null });
                    setState('idle');
                    setShowChatFlow(true);
                  }}
                >
                  Nhập lại thông tin
                </button>
              )}

              {/* Subtle customize toggle */}
              <button
                className={styles.customizeToggle}
                onClick={() => setShowInputForm(v => !v)}
              >
                {showInputForm ? '— Thu gọn' : '+ Tuỳ chỉnh đầu vào'}
              </button>

              {showInputForm && (
                <div className={styles.inputDrawer}>
                  <div className={styles.inputRow}>
                    <label className={styles.inputLabel}>Kỹ năng</label>
                    <input
                      className={styles.inputField}
                      type="text"
                      value={input.profile.skills.join(', ')}
                      onChange={(e) => handleSkillsChange(e.target.value)}
                      placeholder={
                        taxonomyLoading
                          ? 'Đang tải...'
                          : skillOptions.slice(0, 3).map(o => o.label).join(', ')
                      }
                    />
                  </div>
                  <div className={styles.inputRow}>
                    <label className={styles.inputLabel}>Sở thích</label>
                    <input
                      className={styles.inputField}
                      type="text"
                      value={input.profile.interests.join(', ')}
                      onChange={(e) => handleInterestsChange(e.target.value)}
                      placeholder={
                        taxonomyLoading
                          ? 'Đang tải...'
                          : interestOptions.slice(0, 3).map(o => o.label).join(', ')
                      }
                    />
                  </div>
                  <div className={styles.inputRow}>
                    <label className={styles.inputLabel}>Học vấn</label>
                    <select
                      className={styles.inputField}
                      value={input.profile.education_level}
                      onChange={(e) => handleEducationChange(e.target.value)}
                      disabled={taxonomyLoading}
                    >
                      {taxonomyLoading
                        ? <option value="">Đang tải...</option>
                        : educationOptions.map(opt => (
                            <option key={opt.id} value={opt.label}>{opt.label}</option>
                          ))
                      }
                    </select>
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* ── PIPELINE STEPS ────────────────────────────────── */}
          <div className={styles.pipelineWrap}>
            {/* Micro accent drums */}
            <DongSonDrumSVG className={`${styles.drumMicro} ${styles.drumMicroA} ${styles.drumRotateSlow}`} />
            <DongSonDrumSVG className={`${styles.drumMicro} ${styles.drumMicroB} ${styles.drumRotateReverse}`} />

            {/* Step 1 — Input Acquisition */}
            <section className={styles.stepSection} data-reveal>
              <div className={`${styles.stepCard} ${styles.stepAlignLeft}`}>
                <div className={styles.stepNumber}>01</div>
                <h2 className={styles.stepTitle}>
                  Bước 1 — <span className={styles.accentKeyword}>Chuẩn hóa</span> đầu vào
                </h2>
                <p className={styles.stepDesc}>
                  Hệ thống tiếp nhận thông tin người dùng và chuyển đổi toàn bộ dữ liệu về một
                  định dạng chuẩn thống nhất. Mục tiêu là loại bỏ nhiễu, đồng bộ cấu trúc và
                  đảm bảo dữ liệu sẵn sàng cho phân tích.
                </p>
                <ul className={styles.stepBullets}>
                  <li><span className={styles.bulletDot} />Thu thập thông tin hồ sơ</li>
                  <li><span className={styles.bulletDot} />Chuẩn hóa ngôn ngữ &amp; cấu trúc</li>
                  <li><span className={styles.bulletDot} />Kiểm tra tính hợp lệ dữ liệu</li>
                </ul>
              </div>
            </section>

            <FlowArrow dir="down-right" />

            {/* Step 2 — LLM Semantic Normalization */}
            <section className={styles.stepSection} data-reveal>
              <div className={`${styles.stepCard} ${styles.stepCardRadial} ${styles.stepAlignRight}`}>
                <div className={styles.stepNumber}>02</div>
                <h2 className={styles.stepTitle}>
                  Bước 2 — Phân tích ngữ nghĩa bằng <span className={styles.accentKeyword}>LLM</span>
                </h2>
                <p className={styles.stepDesc}>
                  Mô hình ngôn ngữ lớn trích xuất đặc trưng ẩn từ dữ liệu người dùng, chuyển
                  đổi thông tin thành biểu diễn ngữ nghĩa có cấu trúc. Điều này giúp hệ thống
                  hiểu sâu ý định và năng lực thực tế.
                </p>
                <ul className={styles.stepBullets}>
                  <li><span className={styles.bulletDot} />Trích xuất đặc trưng tiềm ẩn</li>
                  <li><span className={styles.bulletDot} />Chuẩn hóa <span className={styles.accentKeyword}>Semantic</span></li>
                  <li><span className={styles.bulletDot} />Loại bỏ nhiễu ngữ cảnh</li>
                </ul>
              </div>
            </section>

            <FlowArrow dir="down-left" />

            {/* Step 3 — Knowledge Base Mapping (horizontal timeline) */}
            <section className={styles.stepSection} data-reveal>
              <div className={`${styles.stepCard} ${styles.stepCardTimeline} ${styles.stepAlignLeft}`}>
                <div className={styles.stepNumber}>03</div>
                <h2 className={styles.stepTitle}>Bước 3 — Ánh xạ cơ sở tri thức</h2>
                <p className={styles.stepDesc}>
                  Dữ liệu sau chuẩn hóa được đối chiếu với kho tri thức nghề nghiệp, thị trường
                  lao động và mô hình kỹ năng. Hệ thống xác định các liên kết phù hợp dựa trên
                  cấu trúc chuẩn hóa.
                </p>
                <div className={styles.timelineRow}>
                  <div className={styles.timelineNode}>Đối chiếu taxonomy nghề nghiệp</div>
                  <div className={styles.timelineConnector} aria-hidden="true" />
                  <div className={styles.timelineNode}>So khớp kỹ năng</div>
                  <div className={styles.timelineConnector} aria-hidden="true" />
                  <div className={styles.timelineNode}>Liên kết dữ liệu thị trường</div>
                </div>
              </div>
            </section>

            <FlowArrow dir="down-right" />

            {/* Step 4 — Deterministic Scoring (HIGHLIGHT) */}
            <section className={styles.stepSection} data-reveal>
              {/* Decorative drum behind Step 4 */}
              <DongSonDrumSVG className={`${styles.drumDecorStep4} ${styles.drumRotateReverse}`} />
              <div className={`${styles.stepCard} ${styles.stepCardHighlight} ${styles.stepAlignCenter}`}>
                <div className={styles.goldHalo} aria-hidden="true" />
                <div className={styles.stepNumberGold}>04</div>
                <h2 className={styles.stepTitleLarge}>
                  Bước 4 — Chấm điểm <span className={styles.accentKeyword}>Xác định</span> (SIMGR Core)
                </h2>
                <p className={styles.stepDesc}>
                  Thuật toán lõi thực hiện tính toán xác định dựa trên ma trận trọng số.
                  Không có yếu tố ngẫu nhiên. Mọi kết quả đều có thể truy vết và kiểm chứng.
                </p>
                <ul className={styles.stepBullets}>
                  <li><span className={styles.bulletDot} />Ma trận trọng số</li>
                  <li><span className={styles.bulletDot} />Tính toán xác định</li>
                  <li><span className={styles.bulletDot} />Đảm bảo khả năng tái lập kết quả</li>
                </ul>
              </div>
            </section>

            <FlowArrow dir="down-left" />

            {/* Step 5 — 6-Stage XAI */}
            <section className={styles.stepSection} data-reveal>
              <div className={`${styles.stepCard} ${styles.stepAlignRight}`}>
                <div className={styles.stepNumber}>05</div>
                <h2 className={styles.stepTitle}>Bước 5 — Giải thích kết quả (6-Stage XAI)</h2>
                <p className={styles.stepDesc}>
                  Hệ thống không chỉ đưa ra kết quả mà còn cung cấp chuỗi giải thích 6 tầng
                  để đảm bảo minh bạch và khả năng hiểu.
                </p>
                <div className={styles.xaiGrid}>
                  {[
                    'Feature Attribution',
                    'Weight Transparency',
                    'Skill Match Breakdown',
                    'Confidence Index',
                    'Comparative Positioning',
                    'Rationale Summary',
                  ].map((stage) => (
                    <div key={stage} className={styles.xaiCard}>{stage}</div>
                  ))}
                </div>
              </div>
            </section>

            <FlowArrow dir="down" />

            {/* Step 6 — Logging & Closed Loop */}
            <section className={`${styles.stepSection} ${styles.stepSectionDark}`} data-reveal>
              <div className={styles.goldDivider} aria-hidden="true" />
              <div className={`${styles.stepCard} ${styles.stepAlignCenter}`}>
                <div className={styles.stepNumber}>06</div>
                <h2 className={styles.stepTitle}>Bước 6 — Giám sát &amp; cải tiến vòng lặp kín</h2>
                <p className={styles.stepDesc}>
                  Hệ thống ghi nhận toàn bộ quy trình phân tích, phục vụ đánh giá hiệu năng và
                  cải tiến liên tục. Không sử dụng dữ liệu cá nhân cho mục đích ngoài hệ thống.
                </p>
                <ul className={styles.stepBullets}>
                  <li><span className={styles.bulletDot} />Logging toàn bộ pipeline</li>
                  <li><span className={styles.bulletDot} />Đánh giá hiệu năng mô hình</li>
                  <li><span className={styles.bulletDot} />Cải tiến định kỳ</li>
                </ul>
              </div>
            </section>

          </div>{/* /pipelineWrap */}

          {/* ── FAQ ───────────────────────────────────────────── */}
          <div className={styles.sectionDivider} aria-hidden="true" style={{ margin: '1rem auto 0' }} />
          <section className={styles.faqSection} data-reveal>
            {/* Decorative drum offset right behind FAQ */}
            <DongSonDrumSVG className={`${styles.drumDecorFaq} ${styles.drumRotateMedium}`} />
            <h2 className={styles.faqTitle}>Câu hỏi thường gặp</h2>
            <div className={styles.faqList}>
              {([
                {
                  q: 'Hệ thống có sử dụng AI không?',
                  a: 'Có, nhưng AI chỉ dùng để trích xuất đặc trưng ngữ nghĩa. Kết quả cuối cùng được tính toán xác định bởi thuật toán lõi SIMGR, không phải LLM.',
                },
                {
                  q: 'Kết quả có thay đổi mỗi lần chạy không?',
                  a: 'Không. Với cùng dữ liệu đầu vào, hệ thống trả về cùng kết quả. Tính xác định (determinism) là nguyên tắc cốt lõi của kiến trúc.',
                },
                {
                  q: 'Dữ liệu cá nhân có được lưu trữ không?',
                  a: 'Dữ liệu được xử lý theo cơ chế logging nội bộ và phục vụ cải tiến hệ thống. Không sử dụng hoặc chia sẻ ngoài mục đích này.',
                },
                {
                  q: 'Hệ thống có thiên lệch không?',
                  a: 'Thuật toán sử dụng ma trận trọng số cố định và có thể kiểm chứng. Mọi điều chỉnh đều minh bạch và có thể truy vết qua audit log.',
                },
                {
                  q: 'Thời gian xử lý bao lâu?',
                  a: 'Phụ thuộc độ phức tạp dữ liệu, thông thường vài giây. Pipeline gồm nhiều tầng xử lý được tối ưu để cho kết quả nhanh nhất có thể.',
                },
                {
                  q: 'Tôi có thể xem lý do vì sao được đề xuất nghề đó không?',
                  a: 'Có. Hệ thống cung cấp pipeline giải thích 6 tầng (XAI) — từ Feature Attribution đến Rationale Summary — đi kèm mỗi kết quả phân tích.',
                },
              ] as { q: string; a: string }[]).map((faq, i) => (
                <div key={i} className={styles.faqItem}>
                  <button
                    className={styles.faqQuestion}
                    onClick={() => setOpenFaq(openFaq === i ? null : i)}
                    aria-expanded={openFaq === i}
                  >
                    <span>{faq.q}</span>
                    <span className={`${styles.faqChevron} ${openFaq === i ? styles.faqChevronOpen : ''}`}>
                      ▾
                    </span>
                  </button>
                  {openFaq === i && (
                    <p className={styles.faqAnswer}>{faq.a}</p>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* ── FINAL CTA ─────────────────────────────────────── */}
          <section className={styles.finalCtaSection} data-reveal>
            <p className={styles.finalCtaEyebrow}>Sẵn sàng bắt đầu?</p>
            <h2 className={styles.finalCtaHeadline}>
              Khám phá con đường{' '}
              <span className={styles.accent}>phù hợp nhất</span> với bạn
            </h2>
            <button
              className={styles.finalCtaBtn}
              onClick={() => setShowChatFlow(true)}
              aria-label="Bắt đầu đánh giá nghề nghiệp"
            >
              Bắt đầu đánh giá
            </button>
          </section>
        </>
      )}

      {/* ── executing ─────────────────────────────────────────────── */}
      {state === 'executing' && (
        <div className={styles.centeredStateWrap}>
          <div className={styles.stage}>
            <div className={styles.pulseRing} />
            <p className={styles.loadingLabel}>Đang phân tích…</p>
            <p className={styles.loadingMeta}>Hệ thống đang xử lý hồ sơ và tính toán kết quả</p>
            <div className={styles.analyzeStages}>
              {[
                'Input Acquisition',
                'Semantic Normalization',
                'Knowledge Mapping',
                'SIMGR Scoring',
                'XAI Explanation',
                'Logging',
              ].map((stage, i) => (
                <div
                  key={stage}
                  className={styles.analyzeStageRow}
                  style={{ animationDelay: `${i * 0.38}s` }}
                >
                  <span className={styles.analyzeStageDot} />
                  <span className={styles.analyzeStageLabel}>{stage}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── success ───────────────────────────────────────────────── */}
      {state === 'success' && result.response && (
        <div className={styles.resultsWrap} style={{ paddingTop: '3rem' }}>
          {/* Top career spotlight */}
          {result.response.top_career && (
            <div className={styles.spotlight}>
              <p className={styles.spotlightLabel}>Nghề nghiệp phù hợp nhất</p>
              <h2 className={styles.spotlightTitle}>{result.response.top_career.name}</h2>
              <div className={styles.spotlightScore}>
                {Math.min(Math.round(result.response.top_career.total_score * 100), 100)}
                <span className={styles.spotlightUnit}>%</span>
              </div>
              <p className={styles.spotlightDomain}>{result.response.top_career.domain}</p>
            </div>
          )}

          {/* Rankings */}
          <div className={styles.card}>
            <h3 className={styles.cardTitle}>Danh sách gợi ý</h3>
            {result.response.rankings.slice(0, 10).map((career, index) => (
              <div key={career.name} className={styles.rankRow}>
                <span className={styles.rankIdx}>{index + 1}</span>
                <div className={styles.rankMeta}>
                  <span className={styles.rankName}>{career.name}</span>
                  <span className={styles.rankDomain}>{career.domain}</span>
                </div>
                <div className={styles.rankBarWrap}>
                  <div className={styles.rankBarFill} style={{ width: `${Math.min(career.total_score * 100, 100)}%` }} />
                </div>
                <span className={styles.rankPct}>{Math.min(Math.round(career.total_score * 100), 100)}%</span>
              </div>
            ))}
          </div>

          {/* Score Breakdown */}
          {result.response.scoring_breakdown && (
            <div className={styles.card}>
              <h3 className={styles.cardTitle}>Phân tích điểm số chi tiết</h3>
              <div className={styles.breakdownGrid}>
                <div className={styles.breakdownItem}>
                  <span className={styles.breakdownLabel}>SIMGR Score</span>
                  <span className={styles.breakdownValue}>
                    {Math.min(Math.round((result.response.scoring_breakdown.ml_score ?? 0) * 100), 100)}%
                  </span>
                </div>
                <div className={styles.breakdownItem}>
                  <span className={styles.breakdownLabel}>Điều chỉnh quy tắc</span>
                  <span className={styles.breakdownValue}>
                    {(result.response.scoring_breakdown.rule_score ?? 0) >= 0 ? '+' : ''}
                    {Math.round((result.response.scoring_breakdown.rule_score ?? 0) * 100)}%
                  </span>
                </div>
                <div className={styles.breakdownItem}>
                  <span className={styles.breakdownLabel}>Phạt rủi ro</span>
                  <span className={styles.breakdownValueNeg}>
                    -{Math.round((result.response.scoring_breakdown.penalty ?? 0) * 100)}%
                  </span>
                </div>
                <div className={styles.breakdownItem}>
                  <span className={styles.breakdownLabel}>Điểm cuối cùng</span>
                  <span className={`${styles.breakdownValue} ${styles.breakdownFinal}`}>
                    {Math.min(Math.round((result.response.scoring_breakdown.final_score ?? 0) * 100), 100)}%
                  </span>
                </div>
              </div>
              {result.response.scoring_breakdown.result_hash && (
                <p className={styles.resultHash}>
                  Hash: {result.response.scoring_breakdown.result_hash.slice(0, 16)}&hellip;
                </p>
              )}
            </div>
          )}

          {/* Explanation — deterministic renderer, never silently blank */}
          {(() => {
            const exp = result.response.explanation;
            if (!isValidExplanation(exp)) {
              return (
                <div className={styles.card} style={{ borderLeft: '4px solid #e53e3e' }}>
                  <h3 className={styles.cardTitle}>Giải thích từ AI</h3>
                  <p style={{ color: '#e53e3e', fontWeight: 600, margin: '0.5rem 0' }}>
                    Explanation payload invalid — backend returned empty or missing data.
                  </p>
                  <span className={styles.confidencePill} style={{ background: '#e53e3e', color: '#fff' }}>
                    trace: {result.response.trace_id}
                  </span>
                </div>
              );
            }

            const structured = normalizeStructuredExplanation(exp.structured_explanation, exp.summary);
            const explanationSummary = structured?.summary ?? exp.summary;
            const factors = Array.isArray(exp.factors) ? exp.factors : [];
            const structuredSections = buildStructuredSections(structured);

            return (
              // key=explainKey forces a DOM remount on every new trace_id,
              // preventing React from reusing a stale fiber with old text
              <div key={explainKey} className={styles.card}>
                <h3 className={styles.cardTitle}>Giải thích từ AI</h3>
                <p className={styles.cardText}>{explanationSummary}</p>

                {structured && (
                  <div className={styles.explainStructured}>
                    {structuredSections.map((section) => (
                      <section key={section.title} className={styles.explainSection}>
                        <h4 className={styles.explainSectionTitle}>{section.title}</h4>
                        <ul className={styles.explainList}>
                          {section.items.map((item, i) => (
                            <li key={`${section.title}-${i}`}>{item}</li>
                          ))}
                        </ul>
                      </section>
                    ))}

                    <p className={styles.confidenceExplain}>{structured.confidence_explanation}</p>
                  </div>
                )}

                {factors.length > 0 && (
                  <div className={styles.factorList}>
                    {factors.map((factor, i) => (
                      <div key={i} className={styles.factorRow}>
                        <span className={styles.factorName}>{factor.name}</span>
                        <span className={factor.contribution >= 0 ? styles.factorPos : styles.factorNeg}>
                          {factor.contribution > 0 ? '+' : ''}{Math.round(factor.contribution * 100)}%
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                <span className={styles.confidencePill}>
                  Độ tin cậy: {Math.min(Math.round(exp.confidence * 100), 100)}%
                </span>
                {/* Debug watermark — confirms this card was rendered from a fresh response */}
                <span style={{ display: 'block', marginTop: '0.4rem', opacity: 0.45, fontSize: '0.68rem', fontFamily: 'monospace' }}>
                  trace: {result.response.trace_id.slice(0, 16)}&hellip;
                </span>
              </div>
            );
          })()}

          {/* Market insights */}
          {result.response.market_insights.length > 0 && (
            <div className={styles.card}>
              <h3 className={styles.cardTitle}>Thông tin thị trường</h3>
              <div className={styles.marketGrid}>
                {result.response.market_insights.slice(0, 3).map((ins, i) => (
                  <div key={i} className={styles.marketTile}>
                    <p className={styles.marketName}>{ins.career_name}</p>
                    <div className={styles.marketBadges}>
                      <span className={`${styles.demandBadge} ${styles[`demand${ins.demand_level}`]}`}>
                        {ins.demand_level === 'HIGH' ? 'Nhu cầu cao' : ins.demand_level === 'MEDIUM' ? 'Trung bình' : 'Thấp'}
                      </span>
                      <span className={styles.growthBadge}>+{Math.round(ins.growth_rate * 100)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* P10: Pipeline Timeline — full lifecycle visualization */}
          {result.response.stage_log && result.response.stage_log.length > 0 && (
            <PipelineTimeline
              stageLog={result.response.stage_log}
              diagnostics={result.response.diagnostics}
            />
          )}

          {/* P10: Rule Hit History */}
          {result.response.rule_applied && result.response.rule_applied.length > 0 && (
            <RuleHitHistory rules={result.response.rule_applied} />
          )}

          {/* P14: Version Trace — model/rule/taxonomy/schema + mismatch detection */}
          {result.response.meta && (
            <VersionTrace
              model_version={result.response.meta.model_version}
              rule_version={result.response.meta.rule_version ?? 'unknown'}
              taxonomy_version={result.response.meta.taxonomy_version ?? 'unknown'}
              schema_version={result.response.meta.schema_version ?? 'unknown'}
              schema_hash={result.response.meta.schema_hash ?? 'unknown'}
              artifact_chain_root={result.response.artifact_hash_chain_root}
            />
          )}

          {/* Meta */}
          <div className={styles.metaRow}>
            <span>{result.response.trace_id}</span>
            <span>{new Date(result.response.timestamp).toLocaleString('vi-VN')}</span>
            <span>{result.response.meta.pipeline_duration_ms}ms</span>
          </div>

          <button className={styles.resetBtn} onClick={handleReset}>
            Phân tích mới
          </button>
        </div>
      )}

      {/* ── ChatFlow overlay — full-screen, shown when user initiates ── */}
      {showChatFlow && (state === 'idle' || state === 'error') && (
        <ChatFlow
          onComplete={handleChatFlowComplete}
          onClose={() => setShowChatFlow(false)}
        />
      )}
    </div>
  );
}
