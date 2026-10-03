const API = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    const problem = await response.json().catch(() => null);
    throw new Error(problem?.detail ?? "请求失败");
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

