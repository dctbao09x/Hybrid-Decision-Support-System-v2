// src/components/features/ChatFlow/ChatFlow.tsx
/**
 * ChatFlow — 6-Step Conversational Data Collection
 * =================================================
 *
 * Architecture:
 *  - 6 sequential chat sessions, one per data category
 *  - Each session asks 3-4 questions before advancing
 *  - No client-side scoring or semantic analysis
 *  - Calls onComplete(data) → parent assembles payload → one API call
 *
 * Constraints:
 *  - No new npm libraries
 *  - No scoring at client
 *  - No backend calls during collection
 *  - Dark + gold design, matching existing palette
 */

import { useState, useRef, useEffect } from 'react';
import styles from './ChatFlow.module.css';

// ═══════════════════════════════════════════════════════════════════
// STEP DEFINITIONS
// ═══════════════════════════════════════════════════════════════════

interface StepQuestion {
  key: string;
  question: string;
  placeholder?: string;
}

interface StepConfig {
  step: number;
  title: string;
  systemStage: string;
  dataField: keyof ChatFlowData;
  questions: StepQuestion[];
}

const STEPS: StepConfig[] = [
  // ─── Step 1: Input Acquisition & Canonicalization ──────────────────────────
  {
    step: 1,
    title: 'Bước 1 — Thu thập hồ sơ cá nhân',
    systemStage: 'Input Acquisition',
    dataField: 'profile_raw',
    questions: [
      {
        key: 'age',
        question: 'Bạn bao nhiêu tuổi?',
        placeholder: 'Nhập số tuổi — ví dụ: 22, 30, 45',
      },
      {
        key: 'employment_status',
        question: 'Bạn hiện đang là học sinh, sinh viên, hay đã đi làm?',
        placeholder: 'Học sinh/Sinh viên / Đi làm /',
      },
      {
        key: 'current_field',
        question: 'Bạn định hướng học hoặc làm việc trong lĩnh vực nào?',
        placeholder: 'Ví dụ: Công nghệ thông tin, Kinh tế, Y tế...',
      },
      {
        key: 'location',
        question: 'Bạn đang sinh sống tại quốc gia / thành phố nào?',
        placeholder: 'Ví dụ: Hà Nội, TP.HCM, Singapore...',
      },
      {
        key: 'mobility',
        question: 'Bạn có sẵn sàng di chuyển địa lý (chuyển thành phố / quốc gia) vì công việc không?',
        placeholder: 'Có / Không',
      },
      {
        key: 'languages',
        question: 'Bạn sử dụng thành thạo ngôn ngữ nào?',
        placeholder: 'Ví dụ: Tiếng Việt, Tiếng Anh, Tiếng Nhật...',
      },
    ],
  },

  // ─── Step 2: Skills & Level Normalization ──────────────────────────────────
  {
    step: 2,
    title: 'Bước 2 — Kỹ năng & mức độ thành thạo',
    systemStage: 'Semantic Normalization',
    dataField: 'skills_input',
    questions: [
      {
        key: 'skills_list',
        question: 'Liệt kê các kỹ năng chính của bạn (phân cách bằng dấu phẩy).',
        placeholder: 'Ví dụ: Python, quản lý dự án, thiết kế UI...',
      },
      {
        key: 'skill_levels',
        question: 'Mức độ thành thạo từng kỹ năng? (Cơ bản / Trung bình / Nâng cao)',
        placeholder: 'Ví dụ: Python: Nâng cao, thiết kế: Trung bình',
      },
      {
        key: 'strongest_skill',
        question: 'Bạn tự tin nhất ở kỹ năng nào?',
        placeholder: 'Tên kỹ năng bạn giỏi nhất',
      },
      {
        key: 'years_used',
        question: 'Tổng số năm kinh nghiệm sử dụng những kỹ năng đó?',
        placeholder: 'Nhập số năm — ví dụ: 0, 2, 5',
      },
      {
        key: 'real_world_used',
        question: 'Bạn đã áp dụng những kỹ năng này trong môi trường làm việc thực tế chưa?',
        placeholder: 'Có / Không',
      },
      {
        key: 'certified',
        question: 'Bạn có chứng chỉ chuyên môn liên quan đến các kỹ năng đó không?',
        placeholder: 'Có / Không — nếu Có, liệt kê ngắn gọn',
      },
    ],
  },

  // ─── Step 3: Knowledge Alignment Preparation ───────────────────────────────
  {
    step: 3,
    title: 'Bước 3 — Sở thích & định hướng ngành',
    systemStage: 'Knowledge Base Mapping',
    dataField: 'interest_raw',
    questions: [
      {
        key: 'work_preference',
        question: 'Bạn thích làm việc với con người, dữ liệu, hay hệ thống / công nghệ?',
        placeholder: 'Con người / Dữ liệu / Hệ thống',
      },
      {
        key: 'environment',
        question: 'Bạn thích môi trường ổn định (quy trình rõ ràng) hay năng động (linh hoạt, sáng tạo)?',
        placeholder: 'Ổn định / Năng động',
      },
      {
        key: 'motivation',
        question: 'Điều gì khiến bạn có động lực làm việc lâu dài?',
        placeholder: 'Ví dụ: Thử thách kỹ thuật, tạo tác động xã hội...',
      },
      {
        key: 'preferred_industry',
        question: 'Bạn ưu tiên ngành nghề cụ thể nào? (phân cách bằng dấu phẩy nếu có nhiều)',
        placeholder: 'Ví dụ: Fintech, Giáo dục, Y tế, AI/ML...',
      },
      {
        key: 'excluded_industry',
        question: 'Bạn có ngành nghề nào không muốn làm không?',
        placeholder: 'Ví dụ: Bán lẻ, Khai khoáng — hoặc gõ "Không"',
      },
      {
        key: 'work_style',
        question: 'Bạn thích làm việc theo nhóm hay độc lập?',
        placeholder: 'Nhóm / Độc lập / Linh hoạt',
      },
    ],
  },

  // ─── Step 4: Education Profiling + SIMGR Scoring Inputs ───────────────────
  {
    step: 4,
    title: 'Bước 4 — Học vấn & kỳ vọng nghề nghiệp',
    systemStage: 'SIMGR Scoring Inputs',
    dataField: 'education_input',
    questions: [
      {
        key: 'degree_level',
        question: 'Trình độ học vấn cao nhất của bạn?',
        placeholder: 'THPT / Cao đẳng / Đại học / Thạc sĩ / Tiến sĩ',
      },
      {
        key: 'field_of_study',
        question: 'Ngành học chính của bạn?',
        placeholder: 'Ví dụ: Khoa học máy tính, Kinh tế học, Kỹ thuật...',
      },
      {
        key: 'certifications',
        question: 'Bạn có chứng chỉ học thuật / chuyên môn nào không?',
        placeholder: 'Liệt kê hoặc gõ "Không"',
      },
      {
        key: 'expected_salary',
        question: 'Mức thu nhập kỳ vọng của bạn là bao nhiêu (triệu đồng/tháng)?',
        placeholder: 'Ví dụ: 15, 20-30, 50...',
      },
      {
        key: 'priority_weight',
        question: 'Điều bạn ưu tiên nhất trong công việc là gì?',
        placeholder: 'Thu nhập / Ổn định / Sáng tạo / Ảnh hưởng xã hội',
      },
      {
        key: 'training_horizon_months',
        question: 'Bạn sẵn sàng đầu tư bao nhiêu tháng để đào tạo / học thêm kỹ năng mới?',
        placeholder: 'Nhập số tháng — ví dụ: 3, 6, 12, 24',
      },
    ],
  },

  // ─── Step 5: Experience Mapping ────────────────────────────────────────────
  {
    step: 5,
    title: 'Bước 5 — Kinh nghiệm thực tế',
    systemStage: 'Experience Mapping',
    dataField: 'experience_data',
    questions: [
      {
        key: 'years',
        question: 'Bạn đã có bao nhiêu năm kinh nghiệm làm việc (bất kể lĩnh vực)?',
        placeholder: 'Nhập số năm — ví dụ: 0, 1, 3, 5',
      },
      {
        key: 'main_role',
        question: 'Vai trò / vị trí chính bạn đã đảm nhận là gì?',
        placeholder: 'Ví dụ: Backend Developer, Kế toán, Data Analyst...',
      },
      {
        key: 'achievements',
        question: 'Thành tựu nghề nghiệp đáng chú ý nhất của bạn?',
        placeholder: 'Ví dụ: Triển khai hệ thống 10k users, tốt nghiệp xuất sắc...',
      },
    ],
  },

  // ─── Step 6: Logging, Explanation & Closed Loop ────────────────────────────
  {
    step: 6,
    title: 'Bước 6 — Tuỳ chỉnh kết quả & hệ thống',
    systemStage: 'Output Alignment',
    dataField: 'goal_raw',
    questions: [
      {
        key: 'target_position',
        question: 'Bạn muốn đạt vị trí nào trong 3–5 năm tới?',
        placeholder: 'Ví dụ: Senior Engineer, CTO, chuyên gia nghiên cứu...',
      },
      {
        key: 'priority',
        question: 'Bạn ưu tiên điều gì nhất trong định hướng nghề nghiệp?',
        placeholder: 'Thu nhập / Cơ hội học hỏi / Sự ổn định',
      },
      {
        key: 'willing_to_switch',
        question: 'Bạn có sẵn sàng chuyển sang ngành nghề hoàn toàn khác không?',
        placeholder: 'Có / Không / Cân nhắc',
      },
      {
        key: 'explanation_depth',
        question: 'Bạn muốn nhận giải thích kết quả ở mức nào?',
        placeholder: 'Chi tiết / Tóm tắt',
      },
      {
        key: 'roadmap_horizon',
        question: 'Bạn muốn nhận lộ trình phát triển trong khung thời gian nào?',
        placeholder: '6 tháng / 3 năm',
      },
      {
        key: 'consent_flag',
        question: 'Bạn có đồng ý chia sẻ dữ liệu ẩn danh để giúp cải thiện hệ thống không?',
        placeholder: 'Có / Không',
      },
      {
        key: 'save_profile',
        question: 'Bạn có muốn lưu hồ sơ này để sử dụng lại trong tương lai không?',
        placeholder: 'Có / Không',
      },
    ],
  },
];

// ═══════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════

export interface ChatFlowData {
  profile_raw: Record<string, string>;
  skills_input: Record<string, string>;
  interest_raw: Record<string, string>;
  education_input: Record<string, string>;
  experience_data: Record<string, string>;
  goal_raw: Record<string, string>;
}

interface ChatMessage {
  role: 'ai' | 'user';
  text: string;
}

interface Props {
  onComplete: (data: ChatFlowData) => void;
  onClose: () => void;
}

const STEP_TRANSITION_DELAY_MS = 350;
const FINAL_HANDOFF_DELAY_MS = 320;

// ═══════════════════════════════════════════════════════════════════
// RADIAL STEP INDICATOR
// ═══════════════════════════════════════════════════════════════════

function RadialStepIndicator({ current, total }: { current: number; total: number }) {
  const cx = 44, cy = 44, r = 34;
  const gapFraction = 0.12; // gap between segments

  const segments = Array.from({ length: total }, (_, i) => {
    const startFraction = (i + gapFraction / 2) / total;
    const endFraction = (i + 1 - gapFraction / 2) / total;
    const startAngle = startFraction * Math.PI * 2 - Math.PI / 2;
    const endAngle = endFraction * Math.PI * 2 - Math.PI / 2;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
    return {
      d: `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`,
      active: i < current,
      current: i === current - 1,
    };
  });

  return (
    <svg className={styles.radialIndicator} viewBox="0 0 88 88" aria-label={`Bước ${current} / ${total}`}>
      {segments.map((seg, i) => (
        <path
          key={i}
          d={seg.d}
          fill="none"
          stroke={
            seg.current
              ? '#d4a24c'
              : seg.active
              ? 'rgba(200,165,90,0.75)'
              : 'rgba(200,165,90,0.15)'
          }
          strokeWidth={seg.current ? 4 : 2.5}
          strokeLinecap="round"
        />
      ))}
      <text
        x={cx}
        y={cy - 5}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="10"
        fill="#c8a55a"
        fontWeight="700"
        fontFamily="inherit"
      >
        {current}
      </text>
      <text
        x={cx}
        y={cy + 7}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="8"
        fill="rgba(200,165,90,0.5)"
        fontFamily="inherit"
      >
        /{total}
      </text>
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════
// AI AVATAR
// ═══════════════════════════════════════════════════════════════════

function AIAvatar({ typing }: { typing: boolean }) {
  return (
    <div className={`${styles.aiAvatar} ${typing ? styles.aiAvatarTyping : ''}`}>
      <svg viewBox="0 0 36 36" className={styles.aiAvatarSvg} aria-hidden="true">
        {/* Outer hex ring */}
        <polygon
          points="18,2 31,9.5 31,26.5 18,34 5,26.5 5,9.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
          opacity="0.7"
        />
        {/* Inner hex */}
        <polygon
          points="18,7 27,12 27,24 18,29 9,24 9,12"
          fill="rgba(200,165,90,0.08)"
          stroke="currentColor"
          strokeWidth="0.8"
          opacity="0.5"
        />
        {/* Centre dot */}
        <circle cx="18" cy="18" r="4" fill="currentColor" opacity="0.85" />
        {/* Rays */}
        {[0, 60, 120, 180, 240, 300].map((deg) => {
          const rad = (deg * Math.PI) / 180;
          return (
            <line
              key={deg}
              x1={18 + Math.cos(rad) * 5.5}
              y1={18 + Math.sin(rad) * 5.5}
              x2={18 + Math.cos(rad) * 9}
              y2={18 + Math.sin(rad) * 9}
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
              opacity="0.6"
            />
          );
        })}
      </svg>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// MESSAGE TEXT RENDERER — supports **bold**
// ═══════════════════════════════════════════════════════════════════

function MsgText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**') ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════

export default function ChatFlow({ onComplete, onClose }: Props) {
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [currentQuestionIdx, setCurrentQuestionIdx] = useState(0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [pendingAnswers, setPendingAnswers] = useState<Record<string, string>>({});
  const [allData, setAllData] = useState<ChatFlowData>({
    profile_raw: {},
    skills_input: {},
    interest_raw: {},
    education_input: {},
    experience_data: {},
    goal_raw: {},
  });
  const [isTyping, setIsTyping] = useState(false);
  const [stepComplete, setStepComplete] = useState(false);
  const [allComplete, setAllComplete] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const currentStep = STEPS[currentStepIdx];
  const totalSteps = STEPS.length;

  // ── Auto-scroll ────────────────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // ── Auto-focus input ───────────────────────────────────────────
  useEffect(() => {
    if (!isTyping && !stepComplete && !allComplete) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isTyping, stepComplete, allComplete, currentQuestionIdx]);

  // ── Initial step intro ─────────────────────────────────────────
  useEffect(() => {
    startStep(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Helpers ────────────────────────────────────────────────────

  function addAIMessage(text: string, delay = 700) {
    setIsTyping(true);
    setTimeout(() => {
      setMessages((prev) => [...prev, { role: 'ai', text }]);
      setIsTyping(false);
    }, delay);
  }

  function startStep(stepIdx: number) {
    const step = STEPS[stepIdx];
    const intro = `**${step.title}**\n\n${step.questions[0].question}`;
    addAIMessage(intro, stepIdx === 0 ? 500 : 600);
  }

  function askQuestion(stepIdx: number, questionIdx: number) {
    const question = STEPS[stepIdx].questions[questionIdx].question;
    addAIMessage(question, 500);
  }

  // ── Submit handler ─────────────────────────────────────────────

  function handleSubmit() {
    const trimmed = inputValue.trim();
    if (!trimmed || isTyping) return;

    // Add user bubble
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }]);
    setInputValue('');

    // Save answer
    const key = currentStep.questions[currentQuestionIdx].key;
    const updatedAnswers = { ...pendingAnswers, [key]: trimmed };
    setPendingAnswers(updatedAnswers);

    const isLastQuestion = currentQuestionIdx >= currentStep.questions.length - 1;

    if (isLastQuestion) {
      // Commit step data
      const dataField = currentStep.dataField;
      const updatedAllData: ChatFlowData = {
        ...allData,
        [dataField]: { ...allData[dataField], ...updatedAnswers },
      };
      setAllData(updatedAllData);
      setPendingAnswers({});

      const isLastStep = currentStepIdx >= totalSteps - 1;

      if (isLastStep) {
        // ALL done
        setMessages((prev) => [
          ...prev,
          {
            role: 'ai',
            text: 'Cảm ơn bạn! Tôi đã thu thập đầy đủ thông tin cần thiết. Hệ thống đang khởi chạy phân tích hồ sơ của bạn...',
          },
        ]);
        setAllComplete(true);
        setTimeout(() => onComplete(updatedAllData), FINAL_HANDOFF_DELAY_MS);
      } else {
        // Step done, prompt next
        addAIMessage(
          `Hoàn tất **Bước ${currentStepIdx + 1}**. Nhấn **"Tiếp theo"** để tiếp tục bước ${currentStepIdx + 2}.`,
          600
        );
        setTimeout(() => setStepComplete(true), STEP_TRANSITION_DELAY_MS);
      }
    } else {
      // Next question in same step
      const nextQIdx = currentQuestionIdx + 1;
      setCurrentQuestionIdx(nextQIdx);
      askQuestion(currentStepIdx, nextQIdx);
    }
  }

  function handleNextStep() {
    const nextStepIdx = currentStepIdx + 1;
    setCurrentStepIdx(nextStepIdx);
    setCurrentQuestionIdx(0);
    setStepComplete(false);
    startStep(nextStepIdx);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  }

  // ── Current question placeholder ───────────────────────────────
  const currentQ = currentStep.questions[currentQuestionIdx];

  // ── Render ─────────────────────────────────────────────────────
  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Đánh giá nghề nghiệp">

      {/* ── Header ──────────────────────────────────────────────── */}
      <header className={styles.header}>
        <RadialStepIndicator
          current={currentStepIdx + (stepComplete || allComplete ? 1 : 0)}
          total={totalSteps}
        />
        <div className={styles.headerText}>
          <span className={styles.headerTitle}>{currentStep.title}</span>
          <span className={styles.headerSub}>{currentStep.systemStage}</span>
        </div>
        <button
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Đóng hội thoại"
          title="Đóng"
        >
          <svg viewBox="0 0 14 14" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <line x1="1" y1="1" x2="13" y2="13" />
            <line x1="13" y1="1" x2="1" y2="13" />
          </svg>
        </button>
      </header>

      {/* ── Messages ────────────────────────────────────────────── */}
      <div className={styles.messagesArea}>

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`${styles.msgRow} ${msg.role === 'ai' ? styles.msgRowAI : styles.msgRowUser}`}
          >
            {msg.role === 'ai' && <AIAvatar typing={false} />}
            <div
              className={`${styles.bubble} ${
                msg.role === 'ai' ? styles.bubbleAI : styles.bubbleUser
              }`}
            >
              <MsgText text={msg.text} />
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {isTyping && (
          <div className={`${styles.msgRow} ${styles.msgRowAI}`}>
            <AIAvatar typing={true} />
            <div className={`${styles.bubble} ${styles.bubbleAI} ${styles.typingBubble}`}>
              <span className={styles.dot} />
              <span className={styles.dot} />
              <span className={styles.dot} />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Input Area ──────────────────────────────────────────── */}
      {!allComplete && (
        <div className={styles.inputArea}>
          {stepComplete ? (
            <button className={styles.nextBtn} onClick={handleNextStep}>
              <span>Tiếp tục: Bước {currentStepIdx + 2}</span>
              <svg viewBox="0 0 18 18" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="3" y1="9" x2="15" y2="9" />
                <polyline points="10,4 15,9 10,14" />
              </svg>
            </button>
          ) : (
            <div className={styles.inputRow}>
              <input
                ref={inputRef}
                className={styles.chatInput}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={currentQ?.placeholder || 'Nhập câu trả lời của bạn...'}
                disabled={isTyping}
                autoComplete="off"
              />
              <button
                className={styles.sendBtn}
                onClick={handleSubmit}
                disabled={isTyping || !inputValue.trim()}
                aria-label="Gửi"
              >
                <svg viewBox="0 0 18 18" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="9" y1="15" x2="9" y2="3" />
                  <polyline points="4,8 9,3 14,8" />
                </svg>
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── All-complete state ───────────────────────────────────── */}
      {allComplete && (
        <div className={styles.completeOverlay}>
          <div className={styles.completePulse} />
          <p className={styles.completeText}>Đang chuẩn bị phân tích…</p>
        </div>
      )}
    </div>
  );
}
