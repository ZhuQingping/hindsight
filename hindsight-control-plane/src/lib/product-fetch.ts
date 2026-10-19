/** Stamp the name rendered in this tab, not a shared cookie that another tab can overwrite. */
export function productFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  if (typeof document === "undefined") return fetch(input, init);
  const name = document.documentElement.dataset.contextdbName;
  const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
  if (!name || url.origin !== window.location.origin) return fetch(input, init);
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  headers.set("X-Product-Name", name);
  return fetch(input, { ...init, headers });
}
