/**
 * Which origin the browser sends API calls to, and why it is not the API's own.
 *
 * The session is an httpOnly cookie carrying `SameSite=Lax`. A browser decides
 * "same site" from the document's hostname, never from CORS headers, so a page
 * served on `http://localhost:3000` that fetches `http://127.0.0.1:8000` is
 * making a cross-site request. The cookie is accepted once and then attached to
 * nothing: the API sees no session, answers 401, and `apiFetch` redirects to
 * /login. That reads exactly like being signed out one instant after signing in,
 * and no amount of CORS configuration changes it, because CORS was never the
 * thing refusing. Safari, which blocks cross-site cookies outright, fails every
 * time; Chrome fails on the SameSite rule alone.
 *
 * So the browser talks to its own origin by default and `next.config.ts` rewrites
 * `/api/v1/*` onward to the API. The cookie is then first-party by construction,
 * and it stops mattering whether the app was opened as localhost, as 127.0.0.1 or
 * over a LAN address. `NEXT_PUBLIC_API_URL` remains an escape hatch for pointing
 * a build at an API that is already deployed somewhere else, and when it names a
 * different site than the page, saying so is better than shipping the same
 * afternoon of confusion to the next person.
 */

export type ApiTarget = {
  /** An absolute origin, or a base that already carries the version prefix. */
  base: string;
  /** Non-null when this arrangement is going to drop the session cookie. */
  warning: string | null;
};

export type ApiTargetEnv = {
  /** `API_INTERNAL_URL`: whatever the Next server itself can reach. */
  internal?: string | undefined;
  /** `NEXT_PUBLIC_API_URL`: baked into the browser bundle at build time. */
  public?: string | undefined;
};

/** Compose's service name. Correct inside that network and nowhere else. */
export const SERVER_FALLBACK = "http://api:8000";

function hostOf(raw: string): string | null {
  try {
    return new URL(raw).hostname;
  } catch {
    return null;
  }
}

/**
 * Approximates the browser's same-site rule. Two hosts are same-site when their
 * registrable domains match, and deciding that exactly needs the public suffix
 * list. Comparing the last two labels is close enough: it catches the mistake
 * this module exists for, `localhost` against `127.0.0.1`, without crying wolf
 * over `api.example.com` against `app.example.com`, which really is same-site.
 */
export function looksSameSite(a: string, b: string): boolean {
  if (a === b) return true;
  const left = a.split(".");
  const right = b.split(".");
  if (left.length < 2 || right.length < 2) return false;
  return left.slice(-2).join(".") === right.slice(-2).join(".");
}

/**
 * @param windowOrigin `window.location.origin`, or null when running on the server.
 */
export function resolveApiTarget(env: ApiTargetEnv, windowOrigin: string | null): ApiTarget {
  if (windowOrigin === null) {
    // Server-side rendering never carries a browser cookie jar, so same-site does
    // not apply and the internal hostname is the right answer.
    return { base: env.internal || env.public || SERVER_FALLBACK, warning: null };
  }

  const override = env.public?.trim();
  if (!override) return { base: windowOrigin, warning: null };

  const apiHost = hostOf(override);
  if (!apiHost) {
    return {
      base: windowOrigin,
      warning: `NEXT_PUBLIC_API_URL is not a URL (${override}), so API calls are going to this origin instead.`,
    };
  }

  const pageHost = hostOf(windowOrigin);
  if (pageHost && !looksSameSite(pageHost, apiHost)) {
    return {
      base: override,
      warning:
        `NEXT_PUBLIC_API_URL points at ${apiHost} but this page was opened on ${pageHost}. ` +
        "The session cookie is SameSite=Lax, so the browser will not send it cross-site and you " +
        "will look signed out the moment you sign in. Either open the app on " +
        `${apiHost}, or unset NEXT_PUBLIC_API_URL and let this origin proxy /api/v1 onward.`,
    };
  }

  return { base: override, warning: null };
}
