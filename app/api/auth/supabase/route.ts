type AuthMode = "signin" | "signup";

type SupabaseUser = {
  id: string;
  email?: string;
  user_metadata?: {
    display_name?: string;
  };
};

type SupabaseAuthResponse = {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: SupabaseUser;
};

function readEnv(name: string, fallbackName?: string) {
  const value = process.env[name]?.trim();
  if (value) {
    return value;
  }

  const fallback = fallbackName ? process.env[fallbackName]?.trim() : "";
  if (fallback) {
    return fallback;
  }

  throw new Error(
    `Missing required environment variable ${name}${fallbackName ? ` or ${fallbackName}` : ""}.`
  );
}

function normalizeSupabaseUrl(value: string) {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

async function readSupabaseError(response: Response) {
  const body = (await response.json().catch(() => null)) as
    | { message?: string; error_description?: string; error?: string }
    | null;
  return (
    body?.message ||
    body?.error_description ||
    body?.error ||
    `${response.status} ${response.statusText}`
  );
}

async function supabaseFetch<T>(
  path: string,
  {
    body,
    method = "POST",
    prefer,
    token,
  }: {
    body?: unknown;
    method?: "POST" | "GET";
    prefer?: string;
    token?: string;
  }
) {
  const supabaseUrl = normalizeSupabaseUrl(readEnv("SUPABASE_URL"));
  const serviceKey = readEnv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY");
  const response = await fetch(`${supabaseUrl}${path}`, {
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${token ?? serviceKey}`,
      "Content-Type": "application/json",
      ...(prefer ? { Prefer: prefer } : {}),
    },
    method,
  });

  if (!response.ok) {
    throw new Error(await readSupabaseError(response));
  }

  return (await response.json().catch(() => null)) as T;
}

async function createAuthUser(email: string, password: string, displayName: string) {
  return supabaseFetch<SupabaseUser>("/auth/v1/admin/users", {
    body: {
      email,
      password,
      email_confirm: true,
      user_metadata: {
        display_name: displayName || email,
      },
    },
  });
}

async function signInWithPassword(email: string, password: string) {
  return supabaseFetch<SupabaseAuthResponse>("/auth/v1/token?grant_type=password", {
    body: {
      email,
      password,
    },
  });
}

async function upsertProfile(user: SupabaseUser, displayName: string) {
  return supabaseFetch<Array<Record<string, unknown>>>(
    "/rest/v1/profiles?on_conflict=id",
    {
      body: {
        id: user.id,
        email: user.email ?? null,
        display_name:
          displayName || user.user_metadata?.display_name || user.email || null,
      },
      prefer: "resolution=merge-duplicates,return=representation",
    }
  );
}

async function appendAuditEvent(
  user: SupabaseUser,
  eventType: "auth.sign_in" | "auth.sign_up"
) {
  return supabaseFetch<Array<Record<string, unknown>>>("/rest/v1/audit_events", {
    body: {
      event_type: eventType,
      actor_id: user.id,
      actor_email: user.email ?? null,
      resource_type: "profile",
      resource_id: user.id,
      metadata: {
        source: "korieo_companion_site",
      },
    },
    prefer: "return=minimal",
  });
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as {
      mode?: AuthMode;
      email?: string;
      password?: string;
      displayName?: string;
    };

    const mode = payload.mode === "signup" ? "signup" : "signin";
    const email = payload.email?.trim().toLowerCase() ?? "";
    const password = payload.password ?? "";
    const displayName = payload.displayName?.trim() ?? "";

    if (!email) {
      return Response.json({ error: "Work email is required." }, { status: 400 });
    }
    if (password.length < 8) {
      return Response.json(
        { error: "Password must be at least 8 characters." },
        { status: 400 }
      );
    }
    if (mode === "signup" && !displayName) {
      return Response.json({ error: "Full name is required." }, { status: 400 });
    }

    if (mode === "signup") {
      await createAuthUser(email, password, displayName);
      const auth = await signInWithPassword(email, password);
      if (!auth.user || !auth.access_token) {
        return Response.json(
          { error: "Supabase created the user but did not return a session." },
          { status: 502 }
        );
      }
      const user = auth.user;
      await upsertProfile(user, displayName);
      await appendAuditEvent(user, "auth.sign_up");

      return Response.json(
        {
          session: {
            accessToken: auth.access_token,
            refreshToken: auth.refresh_token,
            expiresIn: auth.expires_in,
          },
          user: {
            id: user.id,
            email: user.email,
            displayName:
              displayName || user.user_metadata?.display_name || user.email,
          },
        },
        { status: 201 }
      );
    }

    const auth = await signInWithPassword(email, password);
    if (!auth.user || !auth.access_token) {
      return Response.json(
        { error: "Supabase did not return an authenticated user." },
        { status: 502 }
      );
    }

    await upsertProfile(auth.user, displayName);
    await appendAuditEvent(auth.user, "auth.sign_in");

    return Response.json({
      session: {
        accessToken: auth.access_token,
        refreshToken: auth.refresh_token,
        expiresIn: auth.expires_in,
      },
      user: {
        id: auth.user.id,
        email: auth.user.email,
        displayName:
          displayName ||
          auth.user.user_metadata?.display_name ||
          auth.user.email,
      },
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Authentication failed.";
    return Response.json({ error: message }, { status: 500 });
  }
}
