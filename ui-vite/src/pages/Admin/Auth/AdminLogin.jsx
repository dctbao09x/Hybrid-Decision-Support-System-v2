import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { adminLogin } from '../../../services/adminAuthApi';
import './AdminLogin.css';

export default function AdminLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const from = location.state?.from || '/admin/feedback';

  const onSubmit = async (event) => {
    event.preventDefault();
    if (username.trim().length < 3) {
      setError('Tên đăng nhập phải có ít nhất 3 ký tự');
      return;
    }
    if (password.length < 6) {
      setError('Mật khẩu phải có ít nhất 6 ký tự');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await adminLogin(username, password);
      navigate(from, { replace: true });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Đăng nhập thất bại');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="admin-login-page">
      <form className="admin-login-card" onSubmit={onSubmit}>
        <h2>Admin Login</h2>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} maxLength={64} autoComplete="username" />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} maxLength={128} autoComplete="current-password" />
        </label>
        {error && <p className="admin-login-error">{error}</p>}
        <button type="submit" disabled={loading}>{loading ? 'Đang đăng nhập...' : 'Đăng nhập'}</button>
      </form>
    </div>
  );
}
