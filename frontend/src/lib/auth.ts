const KEY = "llm_model_probe_token";

export const auth = {
  get: (): string => localStorage.getItem(KEY) ?? "",
  set: (token: string): void => localStorage.setItem(KEY, token),
  clear: (): void => localStorage.removeItem(KEY),
};

export class UnauthorizedError extends Error {
  constructor() {
    super("unauthorized");
    this.name = "UnauthorizedError";
  }
}
