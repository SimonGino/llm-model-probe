import { useState } from "react";
import { api } from "@/lib/api";
import { auth, UnauthorizedError } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginScreen({
  onSuccess,
}: {
  onSuccess: () => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setBusy(true);
    setError(null);
    auth.set(token.trim());
    try {
      await api.authCheck();
      onSuccess();
    } catch (err) {
      auth.clear();
      if (err instanceof UnauthorizedError) {
        setError("Token 无效");
      } else {
        setError(`${err}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 border rounded-lg p-6 bg-card"
      >
        <div>
          <h1 className="text-xl font-bold">llm-model-probe</h1>
          <p className="text-sm text-muted-foreground mt-1">
            访问需要 token
          </p>
        </div>
        <div className="space-y-1">
          <Label htmlFor="token">Access token</Label>
          <Input
            id="token"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoFocus
            disabled={busy}
          />
        </div>
        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}
        <Button
          type="submit"
          disabled={busy || !token.trim()}
          className="w-full"
        >
          {busy ? "校验中…" : "Continue"}
        </Button>
      </form>
    </div>
  );
}
