export interface AdminSessionPayload {
  accessToken: string;
  refreshToken: string;
  csrfToken: string;
  admin: {
    adminId?: string;
    role?: string;
    permissions?: string[];
  };
}

export interface StoredAdminSession {
  accessToken: string;
  refreshToken: string;
  csrfToken: string;
  admin: {
    adminId?: string;
    role?: string;
    permissions: string[];
  };
}

export function saveAdminSession(payload: AdminSessionPayload): void;
export function clearAdminSession(): void;
export function getAdminSession(): StoredAdminSession;
export function isAdminAuthenticated(): boolean;
