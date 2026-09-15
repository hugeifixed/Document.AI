import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "@/api/client";
import { safeReturnPath } from "@/auth/redirect";
import { useSession } from "@/auth/Session";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ThemeToggle } from "@/components/ThemeToggle";
import { AsyncButton, BrandMark } from "@/components/ui";

const schema = z.object({
  username: z.string().trim().min(1, "Enter your username.").max(150),
  password: z.string().min(1, "Enter your password."),
});
type Form = z.infer<typeof schema>;

export function Login() {
  const { user, expired, signIn } = useSession();
  const [params] = useSearchParams();
  const next = safeReturnPath(params.get("next"));
  const { register, handleSubmit, resetField, setError, setFocus, formState: { errors, isSubmitting } } = useForm<Form>({
    resolver: zodResolver(schema), defaultValues: { username: "", password: "" },
  });
  const error = errors.root?.message;
  useEffect(() => {
    setFocus("username");
  }, [setFocus]);

  async function submit({ username, password }: Form) {
    try { await signIn(username, password); }
    catch (failure) {
      const apiError = failure as ApiError;
      resetField("password");
      setError("root", { message: apiError.code === "INVALID_CREDENTIALS" ? "Username or password is incorrect. Please try again."
        : apiError.status === 403 ? "Your sign-in form expired. Please try again."
        : apiError.status === 429 ? "Too many sign-in attempts. Please wait a minute and try again."
        : "We couldn’t sign you in. Check your connection and try again." });
    }
  }

  if (user) return <Navigate to={next} replace />;
  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-base-200">
      <div aria-hidden="true" className="pointer-events-none absolute -right-52 -bottom-72 size-[52rem] rounded-full opacity-90" style={{ background: "radial-gradient(closest-side, var(--color-blue-soft) 0%, transparent 72%)" }} />
      <header className="relative flex items-center justify-between gap-4 p-4 sm:p-6">
        <span className="flex items-center gap-2.5 font-semibold tracking-tight"><BrandMark size={28} />DocAI</span>
        <ThemeToggle />
      </header>
      <main className="relative grid flex-1 place-items-center px-4 pb-16 pt-8">
        <section className="card card-border grid w-full max-w-md overflow-hidden border-base-300 bg-base-100 shadow-(--shadow-overlay) md:max-w-3xl md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]" aria-labelledby="login-title">
          <div className="card-body gap-6 p-6 sm:p-8">
            <div><h1 id="login-title">Sign in to DocAI</h1><p className="mt-2 text-sm text-secondary">Access your documents, workflows, and reviews.</p></div>
            {expired && <output className="text-sm">Your session has ended. Sign in to continue.</output>}
            <form className="space-y-5" onSubmit={handleSubmit(submit)} aria-busy={isSubmitting} noValidate>
              <div>
                <label className="mb-2 block font-medium" htmlFor="username">Username</label>
                <input id="username" className="input w-full border-(--border-interactive)" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={150} {...register("username")} aria-invalid={!!errors.username} aria-describedby={errors.username ? "username-error" : error ? "login-error" : undefined} />
                {errors.username && <span id="username-error" className="mt-2 block text-sm text-error">{errors.username.message}</span>}
              </div>
              <div>
                <label className="mb-2 block font-medium" htmlFor="password">Password</label>
                <input id="password" type="password" className="input w-full border-(--border-interactive)" autoComplete="current-password" required {...register("password")} aria-invalid={!!errors.password} aria-describedby={errors.password ? "password-error" : error ? "login-error" : undefined} />
                {errors.password && <span id="password-error" className="mt-2 block text-sm text-error">{errors.password.message}</span>}
              </div>
              {error && <ErrorNotice id="login-error" message={error} />}
              <AsyncButton type="submit" className="btn btn-primary w-full" pending={isSubmitting} pendingLabel="Signing in…">Sign in</AsyncButton>
            </form>
            <p className="text-sm text-secondary">Use your DocAI account. If you need access, contact your administrator.</p>
          </div>
          <aside aria-label="About DocAI" className="relative hidden flex-col justify-end gap-3 overflow-hidden p-8 text-white md:flex" style={{ background: "linear-gradient(160deg, #0b2e52 0%, #0069aa 100%)" }}>
            <svg aria-hidden="true" width="380" height="380" viewBox="0 0 380 380" className="absolute -top-16 -right-28 opacity-25"><circle cx="190" cy="190" r="170" fill="none" stroke="currentColor" /><circle cx="190" cy="190" r="120" fill="none" stroke="currentColor" /><circle cx="190" cy="190" r="70" fill="none" stroke="currentColor" /></svg>
            <span aria-hidden="true" className="absolute top-7 left-8 h-1.5 w-9 rounded-full bg-accent" />
            <p className="relative text-xl font-semibold leading-snug tracking-tight text-balance">Every extracted field, grounded in the page it came from.</p>
            <p className="relative text-sm leading-relaxed text-white/80">Confidence scores, provenance, and an audit trail on every run, so reviewers spend time only where the model is unsure.</p>
          </aside>
        </section>
      </main>
    </div>
  );
}
