import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "@/api/client";
import { safeReturnPath } from "@/auth/redirect";
import { useSession } from "@/auth/Session";
import { ErrorNotice } from "@/components/ErrorNotice";
import { AsyncButton } from "@/components/ui";
import { usePrefs, type Theme } from "@/store/prefs";

const schema = z.object({
  username: z.string().trim().min(1, "Enter your username.").max(150),
  password: z.string().min(1, "Enter your password."),
});
type Form = z.infer<typeof schema>;

export function Login() {
  const { user, expired, signIn } = useSession();
  const [params] = useSearchParams();
  const next = safeReturnPath(params.get("next"));
  const { theme, setTheme } = usePrefs();
  const { register, handleSubmit, resetField, setError, setFocus, formState: { errors, isSubmitting } } = useForm<Form>({
    resolver: zodResolver(schema), defaultValues: { username: "", password: "" },
  });
  const error = errors.root?.message;
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Sign in · DocAI";
    setFocus("username");
    return () => { document.title = previousTitle; };
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
    <div className="flex min-h-screen flex-col bg-base-200">
      <header className="flex items-center justify-between gap-4 p-4 sm:p-6">
        <span className="flex items-center gap-2 font-semibold"><span className="size-6 rounded bg-accent" aria-hidden="true" />DocAI</span>
        <label className="flex items-center gap-2 text-sm">Theme
          <select className="select select-sm w-auto border-(--border-interactive)" value={theme} onChange={(event) => setTheme(event.target.value as Theme)}>
            <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
          </select>
        </label>
      </header>
      <main className="grid flex-1 place-items-center px-4 pb-16 pt-8">
        <section className="card card-border w-full max-w-md bg-base-100" aria-labelledby="login-title">
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
        </section>
      </main>
    </div>
  );
}
