import catalogs from "./contextdb-catalogs.json";

type Messages = { [key: string]: string | Messages };

/** Untranslated ContextDB labels share English defaults, preserving local overrides. */
export function withContextdbMessages<T extends Messages>(messages: T, locale: string) {
  const translated = catalogs[locale as keyof typeof catalogs];
  return { ...messages, contextDB: { ...catalogs.en, ...translated } };
}

/** Keep native catalogs and protocol identifiers intact; only relabel UI copy. */
export function contextdbWorkspaceMessages<T extends Messages>(messages: T, locale: string): T {
  const chinese = locale === "zh-CN" || locale === "zh-TW" || locale === "yue-Hant";
  const simplified = locale === "zh-CN";
  if (!chinese && locale !== "en") return messages;

  const overview = chinese
    ? simplified
      ? "工作空间是独立的记忆与知识容器。空间之间隔离，获授权的用户共享同一空间中的内容。"
      : "工作空間是獨立的記憶與知識容器。空間之間隔離，獲授權的使用者共享同一空間中的內容。"
    : "Each workspace stores its own memories and knowledge. Workspaces are isolated; authorized users share the content within a workspace.";
  const empty = chinese
    ? simplified
      ? "还没有工作空间。创建一个工作空间，开始存储记忆与知识。"
      : "還沒有工作空間。建立一個工作空間，開始儲存記憶與知識。"
    : "No workspaces yet. Create a workspace to start storing memories and knowledge.";

  function relabel(catalog: Messages, prefix = ""): Messages {
    return Object.fromEntries(
      Object.entries(catalog).map(([key, value]) => {
        const path = prefix ? `${prefix}.${key}` : key;
        if (typeof value !== "string") return [key, relabel(value, path)];
        if (path === "banksOverview.subtitle") return [key, overview];
        if (path === "banksOverview.welcomeBody" || path === "nav.bank.empty") return [key, empty];
        if (chinese) {
          return [key, value.replace(/记忆库/g, "工作空间").replace(/記憶庫/g, "工作空間")];
        }
        // Exclude ICU arguments ({bank}), identifiers (bank_id), and rich-text
        // tags (bankName), which consumers still expect unchanged.
        return [
          key,
          value.replace(/(?<![\w{])(?:memory )?banks?(?![\w}])/gi, (term) => {
            const workspace = /s$/i.test(term) ? "workspaces" : "workspace";
            return /^[A-Z]/.test(term)
              ? workspace[0].toUpperCase() + workspace.slice(1)
              : workspace;
          }),
        ];
      })
    );
  }

  // Only string values change; catalog keys and nesting retain their input type.
  return relabel(messages) as T;
}
