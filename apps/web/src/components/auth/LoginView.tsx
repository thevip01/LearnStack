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
                disabled={!email.trim() || !password}
              >
                {intent === "signin" ? "Sign in" : "Create account"}
              </Button>
            </form>
          </CardBody>
        </Card>

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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "password";
  autoComplete?: string;
  required?: boolean;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-2xs text-muted">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-md border border-line bg-canvas px-2.5 text-sm text-ink placeholder:text-faint focus:border-accent/50"
      />
    </label>
  );
}
