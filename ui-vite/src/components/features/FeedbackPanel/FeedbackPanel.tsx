// src/components/features/FeedbackPanel/FeedbackPanel.tsx
/**
 * Feedback Panel Component (Stage 7)
 * 
 * Reusable feedback collection component.
 * 
 * Props:
 *   - traceId: Required - trace_id from API response
 *   - confidence: Optional - model confidence
 *   - source: Required - analyze | recommend | chat
 *   - onSubmit: Optional - callback after successful submit
 * 
 * Constraints:
 *   - Will NOT render if traceId is missing
 *   - Cannot submit without correction (≥20 chars)
 *   - Cannot edit after submission (locked state)
 *   - No caching of form data
 */

import React, { useState, useCallback, useEffect, useMemo } from 'react';
import {
  submitFeedback,
  validateFeedback,
} from '../../../services/feedbackApi';
import {
  getPanelState,
  showFeedback,
  markSubmitted,
  lockFeedback,
  shouldAutoShowFeedback,
  canShowFeedback,
} from '../../../store/feedbackStore';
import type {
  FeedbackSource,
  FeedbackPanelState,
  FeedbackFormData,
  ScoreSnapshot,
} from '../../../types/feedback';
import './FeedbackPanel.css';

/**
 * Get or create session ID for tracking
 */
function getOrCreateSessionId(): string {
  const key = 'feedback_session_id';
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const next = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  sessionStorage.setItem(key, next);
  return next;
}

/**
 * Get user profile from localStorage (immutable clone)
 */
function getProfileSnapshot(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem('userProfile');
    if (!raw) return {};
    const profile = JSON.parse(raw);
    // Return frozen deep clone to ensure immutability
    return JSON.parse(JSON.stringify(profile));
  } catch {
    return {};
  }
}

interface FeedbackPanelProps {
  traceId: string;
  confidence?: number;
  source: FeedbackSource;
  onSubmit?: (feedbackId: string) => void;
  onClose?: () => void;
  autoShow?: boolean;  // Trigger auto-show policy
  compact?: boolean;   // Compact mode for inline display
  
  // === RETRAIN-GRADE REQUIRED PROPS (2026-02-20) ===
  careerId: string;           // Career being rated (REQUIRED)
  rankPosition: number;       // Rank at feedback time from backend rank field (REQUIRED)
  scoreSnapshot: ScoreSnapshot; // Scores from original response (REQUIRED)
  modelVersion: string;       // Model version from TraceMeta (REQUIRED)
  kbVersion?: string;         // KB version from TraceMeta
}

const LABELS = {
  title: 'Phản hồi của bạn',
  subtitle: 'Giúp chúng tôi cải thiện',
  rating_label: 'Đánh giá',
  correction_label: 'Gợi ý điều chỉnh',
  correction_placeholder: 'Nghề nghiệp nào phù hợp hơn? Tại sao? (tối thiểu 20 ký tự)',
  reason_label: 'Lý do',
  reason_placeholder: 'Lý do cho đánh giá của bạn (tối thiểu 10 ký tự)',
  submit: 'Gửi phản hồi',
  submitting: 'Đang gửi...',
  success_title: 'Cảm ơn bạn!',
  success_message: 'Phản hồi của bạn đã được ghi nhận và sẽ giúp cải thiện hệ thống.',
  locked_message: 'Bạn đã gửi phản hồi cho kết quả này.',
  missing_trace: 'Không thể gửi phản hồi - thiếu thông tin truy vết.',
  close: 'Đóng',
};

const STAR_COUNT = 5;

/**
 * Star rating component
 */
function StarRating({ 
  value, 
  onChange, 
  disabled 
}: { 
  value: number; 
  onChange: (v: number) => void; 
  disabled: boolean;
}) {
  const [hovered, setHovered] = useState(0);
  
  return (
    <div className="feedback-stars" role="radiogroup" aria-label="Rating">
      {Array.from({ length: STAR_COUNT }, (_, i) => i + 1).map((star) => (
        <button
          key={star}
          type="button"
          className={`feedback-star ${star <= (hovered || value) ? 'active' : ''}`}
          onClick={() => !disabled && onChange(star)}
          onMouseEnter={() => !disabled && setHovered(star)}
          onMouseLeave={() => setHovered(0)}
          disabled={disabled}
          aria-label={`${star} star${star > 1 ? 's' : ''}`}
          aria-checked={star === value}
          role="radio"
        >
          ★
        </button>
      ))}
      <span className="feedback-rating-text">
        {value > 0 ? `${value}/5` : 'Chưa đánh giá'}
      </span>
    </div>
  );
}

export default function FeedbackPanel({
  traceId,
  confidence = 0,
  source,
  onSubmit,
  onClose,
  autoShow = true,
  compact = false,
  // Retrain-grade required props
  careerId,
  rankPosition,
  scoreSnapshot,
  modelVersion,
  kbVersion,
}: FeedbackPanelProps) {
  // State
  const [panelState, setPanelState] = useState<FeedbackPanelState>(() => getPanelState(traceId));
  const [showPanel, setShowPanel] = useState(false);
  const [formData, setFormData] = useState<FeedbackFormData>({
    rating: 0,
    correction: '',
    reason: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [feedbackId, setFeedbackId] = useState<string | null>(null);
  
  // Check if trace is valid
  const hasValidTrace = useMemo(() => {
    return Boolean(traceId && traceId.trim());
  }, [traceId]);
  
  // Validate retrain-grade required props
  const hasValidRetrainContext = useMemo(() => {
    return Boolean(
      careerId && 
      rankPosition >= 1 && 
      scoreSnapshot?.matchScore !== undefined &&
      modelVersion
    );
  }, [careerId, rankPosition, scoreSnapshot, modelVersion]);
  
  // Don't render if no trace
  if (!hasValidTrace) {
    console.warn('[FeedbackPanel] Missing traceId - not rendering');
    return null;
  }
  
  // Warn if missing retrain context (but still render)
  if (!hasValidRetrainContext) {
    console.warn('[FeedbackPanel] Missing retrain-grade context:', {
      careerId,
      rankPosition,
      hasMatchScore: scoreSnapshot?.matchScore !== undefined,
      modelVersion,
    });
  }
  
  // Check locked state on mount
  useEffect(() => {
    const state = getPanelState(traceId);
    setPanelState(state);
    
    if (state === 'submitted' || state === 'locked') {
      setShowPanel(true);  // Show locked message
    } else if (autoShow && shouldAutoShowFeedback(traceId, confidence)) {
      // Auto-trigger on low confidence
      setTimeout(() => {
        if (canShowFeedback(traceId)) {
          showFeedback(traceId);
          setPanelState('shown');
          setShowPanel(true);
        }
      }, 3000);  // Delay 3s before showing
    }
  }, [traceId, confidence, autoShow]);
  
  // Handle show panel manually
  const handleShowPanel = useCallback(() => {
    if (canShowFeedback(traceId)) {
      showFeedback(traceId);
      setPanelState('shown');
      setShowPanel(true);
    }
  }, [traceId]);
  
  // Handle close (only if not submitted)
  const handleClose = useCallback(() => {
    if (panelState !== 'submitted' && panelState !== 'locked') {
      setShowPanel(false);
      onClose?.();
    }
  }, [panelState, onClose]);
  
  // Handle rating change
  const handleRatingChange = useCallback((rating: number) => {
    if (panelState === 'submitted' || panelState === 'locked') return;
    setFormData(prev => ({ ...prev, rating }));
    setErrors(prev => ({ ...prev, rating: '' }));
  }, [panelState]);
  
  // Handle correction change
  const handleCorrectionChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (panelState === 'submitted' || panelState === 'locked') return;
    const value = e.target.value;
    setFormData(prev => ({ ...prev, correction: value }));
    if (value.length >= 20) {
      setErrors(prev => ({ ...prev, correction: '' }));
    }
  }, [panelState]);
  
  // Handle reason change
  const handleReasonChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (panelState === 'submitted' || panelState === 'locked') return;
    const value = e.target.value;
    setFormData(prev => ({ ...prev, reason: value }));
    if (value.length >= 10) {
      setErrors(prev => ({ ...prev, reason: '' }));
    }
  }, [panelState]);
  
  // Validate form
  const validateForm = useCallback((): boolean => {
    const validation = validateFeedback({
      trace_id: traceId,
      rating: formData.rating,
      correction: { correct_career: formData.correction },
      reason: formData.reason,
      source,
    });
    
    setErrors(validation.errors);
    return validation.valid;
  }, [traceId, formData, source]);
  
  // Handle submit
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (panelState === 'submitted' || panelState === 'locked') {
      return;
    }
    
    if (!validateForm()) {
      return;
    }
    
    // Validate retrain-grade context
    if (!hasValidRetrainContext) {
      setSubmitError('Missing required context for feedback (career, rank, score, model version)');
      return;
    }
    
    setSubmitting(true);
    setSubmitError(null);
    
    try {
      // Compute explicit_accept from rating
      // rating >= 4 = accept, rating <= 2 = reject, 3 = neutral (false)
      const explicitAccept = formData.rating >= 4;
      
      // Get profile snapshot (immutable clone)
      const profileSnapshot = getProfileSnapshot();
      if (Object.keys(profileSnapshot).length === 0) {
        console.warn('[FeedbackPanel] Empty profile snapshot - feedback may have reduced training value');
      }
      
      const response = await submitFeedback({
        // Existing fields
        trace_id: traceId,
        rating: formData.rating,
        correction: { correct_career: formData.correction },
        reason: formData.reason,
        source,
        
        // Retrain-grade required fields
        career_id: careerId,
        rank_position: rankPosition, // From backend rank field, NOT array index
        score_snapshot: scoreSnapshot, // From original response, NOT recalculated
        profile_snapshot: profileSnapshot, // Immutable clone from localStorage
        model_version: modelVersion,
        explicit_accept: explicitAccept,
        
        // Optional fields
        kb_version: kbVersion,
        confidence,
        session_id: getOrCreateSessionId(),
      });
      
      // Mark as submitted in store
      markSubmitted(traceId, response.feedback_id);
      lockFeedback(traceId);
      
      setFeedbackId(response.feedback_id);
      setPanelState('locked');
      
      onSubmit?.(response.feedback_id);
      
      if (import.meta.env.DEV) {
        console.log('[FeedbackPanel] Submitted successfully:', response.feedback_id, {
          career_id: careerId,
          rank_position: rankPosition,
          model_version: modelVersion,
          explicit_accept: explicitAccept,
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Submission failed';
      setSubmitError(message);
      console.error('[FeedbackPanel] Submit error:', err);
    } finally {
      setSubmitting(false);
    }
  }, [traceId, formData, source, panelState, validateForm, onSubmit, hasValidRetrainContext, careerId, rankPosition, scoreSnapshot, modelVersion, kbVersion, confidence]);
  
  // Determine component class
  const panelClass = [
    'feedback-panel',
    compact ? 'compact' : '',
    showPanel ? 'visible' : '',
    panelState,
  ].filter(Boolean).join(' ');
  
  // Render locked state
  if (panelState === 'submitted' || panelState === 'locked') {
    return (
      <div className={panelClass}>
        <div className="feedback-success">
          <div className="feedback-success-icon">✓</div>
          <h4>{LABELS.success_title}</h4>
          <p>{LABELS.success_message}</p>
          {feedbackId && (
            <p className="feedback-id">ID: {feedbackId}</p>
          )}
        </div>
      </div>
    );
  }
  
  // Render trigger button if not shown
  if (!showPanel) {
    return (
      <button
        type="button"
        className="feedback-trigger"
        onClick={handleShowPanel}
        aria-label="Open feedback panel"
      >
        <span className="feedback-trigger-icon">💬</span>
        <span className="feedback-trigger-text">Gửi phản hồi</span>
      </button>
    );
  }
  
  // Render form
  return (
    <div className={panelClass}>
      <div className="feedback-header">
        <div className="feedback-title">
          <h4>{LABELS.title}</h4>
          <p className="feedback-subtitle">{LABELS.subtitle}</p>
        </div>
        <button
          type="button"
          className="feedback-close"
          onClick={handleClose}
          aria-label={LABELS.close}
        >
          ×
        </button>
      </div>
      
      <form className="feedback-form" onSubmit={handleSubmit}>
        {/* Rating */}
        <div className="feedback-field">
          <label className="feedback-label">{LABELS.rating_label}</label>
          <StarRating
            value={formData.rating}
            onChange={handleRatingChange}
            disabled={submitting}
          />
          {errors.rating && (
            <span className="feedback-error">{errors.rating}</span>
          )}
        </div>
        
        {/* Correction */}
        <div className="feedback-field">
          <label className="feedback-label">
            {LABELS.correction_label}
            <span className="feedback-char-count">
              {formData.correction.length}/20+
            </span>
          </label>
          <textarea
            className={`feedback-textarea ${errors.correction ? 'error' : ''}`}
            value={formData.correction}
            onChange={handleCorrectionChange}
            placeholder={LABELS.correction_placeholder}
            disabled={submitting}
            rows={3}
            maxLength={2000}
          />
          {errors.correction && (
            <span className="feedback-error">{errors.correction}</span>
          )}
        </div>
        
        {/* Reason */}
        <div className="feedback-field">
          <label className="feedback-label">
            {LABELS.reason_label}
            <span className="feedback-char-count">
              {formData.reason.length}/10+
            </span>
          </label>
          <textarea
            className={`feedback-textarea ${errors.reason ? 'error' : ''}`}
            value={formData.reason}
            onChange={handleReasonChange}
            placeholder={LABELS.reason_placeholder}
            disabled={submitting}
            rows={2}
            maxLength={500}
          />
          {errors.reason && (
            <span className="feedback-error">{errors.reason}</span>
          )}
        </div>
        
        {/* Submit error */}
        {submitError && (
          <div className="feedback-submit-error">
            {submitError}
          </div>
        )}
        
        {/* Submit button */}
        <button
          type="submit"
          className="feedback-submit"
          disabled={submitting}
        >
          {submitting ? LABELS.submitting : LABELS.submit}
        </button>
        
        {/* Trace ID (hidden, for debugging) */}
        <input type="hidden" name="trace_id" value={traceId} />
      </form>
      
      {/* Confidence indicator */}
      {confidence > 0 && confidence < 0.8 && (
        <div className="feedback-confidence-notice">
          <span className="notice-icon">ℹ️</span>
          <span>Độ tin cậy thấp ({Math.round(confidence * 100)}%) - phản hồi sẽ giúp cải thiện</span>
        </div>
      )}
    </div>
  );
}
