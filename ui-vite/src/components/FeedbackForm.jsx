import { useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { submitUserFeedback } from '../services/adminFeedbackApi';
import './FeedbackForm.css';

const CATEGORIES = ['UI/UX', 'Recommendation', 'Performance', 'Bug', 'Other'];

function getOrCreateSessionId() {
  const key = 'feedback_session_id';
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const next = `sess_${Math.random().toString(36).slice(2, 12)}`;
  sessionStorage.setItem(key, next);
  return next;
}

function getUserId() {
  const profileRaw = localStorage.getItem('userProfile');
  if (profileRaw) {
    try {
      const profile = JSON.parse(profileRaw);
      if (profile?.id) return String(profile.id);
      if (profile?.fullName) return `user_${String(profile.fullName).replace(/\s+/g, '_').toLowerCase()}`;
    } catch {
      return `user_${Math.random().toString(36).slice(2, 10)}`;
    }
  }
  return `user_${Math.random().toString(36).slice(2, 10)}`;
}

export default function FeedbackForm() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState('');
  const [error, setError] = useState('');
  const timestamp = useMemo(() => new Date().toISOString(), [open]);

  const [form, setForm] = useState({
    user_id: getUserId(),
    email: '',
    rating: 5,
    category: CATEGORIES[0],
    message: '',
    screenshot: '',
  });

  const onFile = (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      setForm((prev) => ({ ...prev, screenshot: '' }));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setForm((prev) => ({ ...prev, screenshot: String(reader.result || '') }));
    };
    reader.readAsDataURL(file);
  };

  const validate = () => {
    if (!form.email || !/^\S+@\S+\.\S+$/.test(form.email)) return 'Email không hợp lệ';
    if (!form.message || form.message.trim().length < 10) return 'Nội dung phải từ 10 ký tự';
    if (form.rating < 1 || form.rating > 5) return 'Rating phải từ 1-5';
    return '';
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setSuccess('');

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      await submitUserFeedback({
        userId: form.user_id,
        email: form.email,
        rating: form.rating,
        category: form.category,
        message: form.message,
        screenshot: form.screenshot || undefined,
        meta: {
          page: window.location.pathname,
          version: import.meta.env.VITE_APP_VERSION || '1.0.0',
          sessionId: getOrCreateSessionId(),
        },
      });
      setSuccess('Gửi phản hồi thành công');
      setForm((prev) => ({ ...prev, message: '', screenshot: '' }));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Gửi phản hồi thất bại');
    } finally {
      setLoading(false);
    }
  };

  if (location.pathname.startsWith('/admin')) {
    return null;
  }

  return (
    <>
      <button className="feedback-open-btn" type="button" onClick={() => setOpen(true)}>
        Gửi phản hồi
      </button>

      {open && (
        <div className="feedback-modal-overlay" role="dialog" aria-modal="true">
          <div className="feedback-modal">
            <div className="feedback-modal-header">
              <h3>Feedback</h3>
              <button type="button" onClick={() => setOpen(false)}>×</button>
            </div>
            <form className="feedback-modal-form" onSubmit={handleSubmit}>
              <label>
                User ID
                <input value={form.user_id} readOnly />
              </label>
              <label>
                Email
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm((prev) => ({ ...prev, email: e.target.value }))}
                  required
                />
              </label>
              <label>
                Rating
                <input
                  type="number"
                  min="1"
                  max="5"
                  value={form.rating}
                  onChange={(e) => setForm((prev) => ({ ...prev, rating: Number(e.target.value) }))}
                  required
                />
              </label>
              <label>
                Category
                <select value={form.category} onChange={(e) => setForm((prev) => ({ ...prev, category: e.target.value }))}>
                  {CATEGORIES.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </label>
              <label>
                Message
                <textarea
                  rows={4}
                  value={form.message}
                  onChange={(e) => setForm((prev) => ({ ...prev, message: e.target.value }))}
                  required
                />
              </label>
              <label>
                Screenshot (optional)
                <input type="file" accept="image/*" onChange={onFile} />
              </label>
              <label>
                Timestamp
                <input value={timestamp} readOnly />
              </label>

              {error && <p className="feedback-error">{error}</p>}
              {success && <p className="feedback-success">{success}</p>}

              <div className="feedback-form-actions">
                <button type="button" onClick={() => setOpen(false)}>Đóng</button>
                <button type="submit" disabled={loading}>{loading ? 'Đang gửi...' : 'Gửi phản hồi'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
