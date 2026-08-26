"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { describeError } from "@/lib/api";
import { useLogin, useRegister } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

type Intent = "signin" | "register";

/**
 * Mirrors `MIN_PASSWORD_LENGTH` in `apps/api/learnos_api/schemas/auth.py`.
 *
 * Duplicated rather than fetched, because a form that cannot state its own rule
 * until a network round trip completes is worse than one number in two files. The
 * two are pinned together by `test_the_register_form_states_the_password_rule` in
 * the API suite, which reads this file and fails if the numbers drift.
 *
 * Stating it at all is the actual fix: registering with an eight character
 * password used to return a 422 whose message was "request body failed
 * validation", so the form showed a rejection that named neither the field nor
 * the rule. The API now says which field and why, and this stops the learner
 * reaching that error in the first place.
 */
const PASSWORD_MIN_LENGTH = 10;

/**
 * The account a fresh checkout already has, and the only admin on it.
 *
 * Mirrors `DEMO_USER_EMAIL` / `DEMO_USER_PASSWORD` in `apps/api/learnos_api/config.py`,
 * pinned by `test_the_sign_in_form_offers_the_seeded_demo_account` so the hint cannot
 * start naming a password that no longer works.
 *
 * Shown only in a development build, and safe to show there for the same reason the
 * account exists there: `Settings.insecure_defaults()` refuses `SEED_DEMO_USER`
 * outside development, so in production there is no such account to leak. Worth
 * showing because `seed.py` makes this user `is_admin`, and nothing else in the app
 * can promote one, so without it the ingestion console and the subject reload are
 * documented but unreachable.
 */
const DEMO = { email: "demo@learnos.dev", password: "learnos-demo-2026" } as const;
const IS_DEV = process.env.NODE_ENV !== "production";

/**
 * Sign in / create account.
 *
 * Reading is anonymous by design, so this page is only reached when a learner
 * wants their progress recorded (or the API answered 401 on a write). It honours
 * `?next=` so a 401 mid-task returns you to the task, not to the catalogue.
 *
 * The session is an httpOnly cookie set by the API; no token is ever written to
 * JS-readable storage here.
 */
export function LoginView({ next }: { next: string | null }) {
  const router = useRouter();
  const [intent, setIntent] = useState<Intent>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");

  const login = useLogin();
  const register = useRegister();
  const active = intent === "signin" ? login : register;
  const destination = next && next.startsWith("/") ? next : routes.subjects;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      if (intent === "signin") {
        await login.mutateAsync({ email: email.trim(), password });
      } else {
        await register.mutateAsync({
          email: email.trim(),
          password,
          ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
        });
      }
      router.replace(destination);
    } catch {
      // The mutation carries the error; the form renders it below.
    }
  }

  const described = active.error ? describeError(active.error) : null;

  return (
    <div className="panel-scroll">
      <div className="mx-auto w-full max-w-sm px-pad py-12">
        <Card>
          <CardHeader
            title={intent === "signin" ? "Sign in" : "Create an account"}
            subtitle={
              intent === "signin"
                ? "Your progress and mastery history follow the account."
                : "Browsing needs no account. One only exists to record what you have mastered."
            }
          />
          <CardBody>
            <div className="mb-4 inline-flex rounded-md border border-line bg-canvas p-0.5">
              {(["signin", "register"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setIntent(option)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                    intent === option ? "bg-accent text-canvas" : "text-muted hover:text-ink",
                  )}
                >
                  {option === "signin" ? "Sign in" : "Register"}
                </button>
              ))}
            </div>

            <form onSubmit={submit} className="space-y-3">
              {intent === "register" ? (
                <LabelledInput
                  label="Display name"
                  value={displayName}
                  onChange={setDisplayName}
                  autoComplete="nickname"
                  placeholder="Optional"
                />
              ) : null}
              <LabelledInput
                label="Email"
                type="email"
                value={email}
                onChange={setEmail}
                autoComplete="email"
                required
              />
              <LabelledInput
                label="Password"
                type="password"
                value={password}
                onChange={setPassword}
                autoComplete={intent === "signin" ? "current-password" : "new-password"}
                required
                minLength={intent === "register" ? PASSWORD_MIN_LENGTH : undefined}
                hint={intent === "register" ? `At least ${PASSWORD_MIN_LENGTH} characters.` : undefined}
              />

              {described ? (
                <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-2 py-1.5 text-2xs text-danger">
                  {described.message}
                </p>
              ) : null}

              <Button
                type="submit"
                variant="primary"
                size="md"
                className="w-full"
                loading={active.isPending}
                disabled={!email.trim() || !password || (intent === "register" && password.length < PASSWORD_MIN_LENGTH)}
              >
                {intent === "signin" ? "Sign in" : "Create account"}
              </Button>
            </form>
          </CardBody>
        </Card>

        {IS_DEV ? (
          <Card className="mt-3">
            <CardBody className="py-pad-sm">
              <p className="text-2xs text-muted">
                Development build. The API seeds one account at startup and makes it an admin, so it is the way into{" "}
                <code className="font-mono text-faint">/admin/ingestion</code>, where subject packages are reloaded and
                extraction candidates are reviewed.
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <code className="font-mono text-2xs text-faint">
                  {DEMO.email} · {DEMO.password}
                </code>
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => {
                    setIntent("signin");
                    setEmail(DEMO.email);
                    setPassword(DEMO.password);
                  }}
                >
                  Use demo admin
                </Button>
              </div>
            </CardBody>
          </Card>
        ) : null}

        <p className="mt-3 text-center text-2xs text-faint">
          The catalogue and every concept stay readable without an account.
        </p>
      </div>
    </div>
  );
}

function LabelledInput({
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  required,
  placeholder,
  minLength,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "password";
  autoComplete?: string;
  required?: boolean;
  placeholder?: string;
  minLength?: number;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-2xs text-muted">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        minLength={minLength}
        placeholder={placeholder}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-md border border-line bg-canvas px-2.5 text-sm text-ink placeholder:text-faint focus:border-accent/50"
      />
      {hint ? <span className="mt-1 block text-2xs text-faint">{hint}</span> : null}
    </label>
  );
}
