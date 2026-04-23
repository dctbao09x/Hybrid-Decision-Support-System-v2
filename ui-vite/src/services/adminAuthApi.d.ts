export interface AdminLoginResponse {
  accessToken: string;
  refreshToken: string;
  csrfToken: string;
  admin: {
    adminId: string;
    role: string;
    permissions: string[];
  };
}

export function adminLogin(username: string, password: string): Promise<AdminLoginResponse>;
export function refreshAdminToken(): Promise<AdminLoginResponse>;
export function adminLogout(): Promise<void>;
