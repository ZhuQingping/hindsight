"use client";

import { productFetch } from "@/lib/product-fetch";
import { Suspense, useState, FormEvent, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LanguageSwitcher } from "@/components/language-switcher";
import { sanitizeReturnTo, withBasePath } from "@/lib/base-path";
import { Brand } from "@/components/brand";
import { Database, Search, Sparkles, ArrowRight, LockKeyhole } from "lucide-react";

function LoginForm() {
  const t = useTranslations("login");
  const tBrand = useTranslations("brand");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  // Validate returnTo to prevent open-redirect via crafted login links.
  const returnTo = sanitizeReturnTo(searchParams.get("returnTo"));

  useEffect(() => {
    // Focus the input on mount
    const input = document.getElementById("access-key");
    input?.focus();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await productFetch(withBasePath("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });

      if (res.ok) {
        // Navigate to the returnTo URL
        router.push(returnTo);
        router.refresh();
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.error || t("invalidKey"));
      }
    } catch {
      setError(t("connectFailed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-dvh bg-background">
      <header className="flex items-center justify-between border-b border-border bg-card px-6 py-5 sm:px-10">
        <Brand />
        <LanguageSwitcher />
      </header>
      <main className="mx-auto grid min-h-[calc(100dvh-82px)] max-w-6xl items-center gap-12 px-6 py-12 md:grid-cols-[1.1fr_1fr] md:gap-16 md:px-10">
        <section className="hidden md:block">
          <p className="mb-6 text-xs font-semibold uppercase tracking-[0.2em] text-primary">
            {tBrand("console")}
          </p>
          <h1 className="max-w-lg text-4xl font-semibold leading-[1.25] tracking-tight lg:text-5xl">
            {tBrand("headline")}
          </h1>
          <p className="mt-6 max-w-md text-base leading-7 text-muted-foreground">
            {tBrand("intro")}
          </p>
          <div className="mt-10 space-y-5">
            {[
              { Icon: Database, label: tBrand("retain"), detail: tBrand("retainDetail") },
              { Icon: Search, label: tBrand("recall"), detail: tBrand("recallDetail") },
              { Icon: Sparkles, label: tBrand("reflect"), detail: tBrand("reflectDetail") },
            ].map(({ Icon, label, detail }) => (
              <div key={label} className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/10 bg-primary/5 text-primary">
                  <Icon className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm font-medium">{label}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
        <section
          aria-labelledby="sign-in-heading"
          className="w-full max-w-md justify-self-center rounded-xl border border-border bg-card p-7 shadow-sm sm:p-10"
        >
          <div className="mb-7">
            <LockKeyhole className="mb-5 h-6 w-6 text-primary" />
            <h2 id="sign-in-heading" className="text-2xl font-semibold tracking-tight">
              {t("title")}
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">{t("description")}</p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <label htmlFor="access-key" className="text-sm font-medium">
                {t("accessKey")}
              </label>
              <Input
                id="access-key"
                type="password"
                placeholder={t("accessKeyPlaceholder")}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                autoComplete="current-password"
                required
                aria-invalid={!!error}
                aria-describedby={error ? "login-error" : undefined}
                className="h-11"
              />
            </div>
            {error && (
              <p id="login-error" role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" className="h-11 w-full gap-2" disabled={loading || !key}>
              {loading ? t("signingIn") : t("signIn")}
              {!loading && <ArrowRight className="h-4 w-4" />}
            </Button>
          </form>
          <p className="mt-7 border-t border-border pt-5 text-xs leading-5 text-muted-foreground">
            {tBrand("localAccess")}
          </p>
        </section>
      </main>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
