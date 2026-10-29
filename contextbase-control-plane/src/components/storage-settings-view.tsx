"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { HardDrive, Loader2, Save, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { BankSelector } from "@/components/bank-selector";

interface FileStorageConfig {
  storage_type: string;
  extension: string | null;
  s3_bucket: string | null;
  s3_region: string | null;
  s3_endpoint: string | null;
  s3_access_key_id: string | null;
  s3_secret_access_key: string | null;
}

const SECRET_MASK = "••••••••";

export function StorageSettingsView() {
  const t = useTranslations("settings.storage");
  const tCommon = useTranslations("common");

  const [config, setConfig] = useState<FileStorageConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Form state
  const [storageType, setStorageType] = useState("native");
  const [s3Bucket, setS3Bucket] = useState("");
  const [s3Region, setS3Region] = useState("");
  const [s3Endpoint, setS3Endpoint] = useState("");
  const [s3AccessKeyId, setS3AccessKeyId] = useState("");
  const [s3SecretAccessKey, setS3SecretAccessKey] = useState("");

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/file-storage/config", { cache: "no-store" });
      if (!res.ok) throw new Error("Failed to load config");
      const data: FileStorageConfig = await res.json();
      setConfig(data);
      setStorageType(data.storage_type || "native");
      setS3Bucket(data.s3_bucket || "");
      setS3Region(data.s3_region || "");
      setS3Endpoint(data.s3_endpoint || "");
      setS3AccessKeyId(data.s3_access_key_id || "");
      setS3SecretAccessKey(data.s3_secret_access_key || "");
    } catch {
      toast.error(t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const body: Record<string, string> = { storage_type: storageType };
      // Only send fields that changed or are non-mask secrets
      if (s3Bucket) body.s3_bucket = s3Bucket;
      if (s3Region) body.s3_region = s3Region;
      if (s3Endpoint) body.s3_endpoint = s3Endpoint;
      if (s3AccessKeyId && s3AccessKeyId !== SECRET_MASK) body.s3_access_key_id = s3AccessKeyId;
      if (s3SecretAccessKey && s3SecretAccessKey !== SECRET_MASK) body.s3_secret_access_key = s3SecretAccessKey;

      const res = await fetch("/api/file-storage/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || "Failed to save");
      }
      const data: FileStorageConfig = await res.json();
      setConfig(data);
      // Update form with masked secrets from response
      setS3AccessKeyId(data.s3_access_key_id || "");
      setS3SecretAccessKey(data.s3_secret_access_key || "");
      setSaved(true);
      toast.success(t("saveSuccess"));
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      toast.error(t("saveError"));
    } finally {
      setSaving(false);
    }
  };

  const isObjectStore = storageType === "s3";

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <BankSelector />
      <div className="flex-1 p-6 max-w-3xl mx-auto w-full">
        <div className="flex items-center gap-2 mb-6">
          <HardDrive className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Spinner />
          </div>
        ) : config?.extension ? (
          <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
            {t("extensionActive", { extension: config.extension })}
          </div>
        ) : (
          <div className="space-y-6">
            <p className="text-sm text-muted-foreground">{t("description")}</p>

            {/* Storage Type */}
            <div className="space-y-2">
              <Label>{t("storageType")}</Label>
              <Select value={storageType} onValueChange={setStorageType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="native">{t("types.native")}</SelectItem>
                  <SelectItem value="s3">{t("types.s3")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* S3 Configuration */}
            {storageType === "s3" && (
              <div className="space-y-4 rounded-lg border border-border p-4">
                <h2 className="font-medium">{t("s3.title")}</h2>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="space-y-2 sm:col-span-2">
                    <Label>{t("s3.bucket")}</Label>
                    <Input value={s3Bucket} onChange={(e) => setS3Bucket(e.target.value)} placeholder="my-bucket" />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("s3.region")}</Label>
                    <Input value={s3Region} onChange={(e) => setS3Region(e.target.value)} placeholder="us-east-1" />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("s3.endpoint")}</Label>
                    <Input value={s3Endpoint} onChange={(e) => setS3Endpoint(e.target.value)} placeholder="https://s3.example.com" />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("s3.accessKeyId")}</Label>
                    <Input value={s3AccessKeyId} onChange={(e) => setS3AccessKeyId(e.target.value)} placeholder={SECRET_MASK} />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("s3.secretAccessKey")}</Label>
                    <Input type="password" value={s3SecretAccessKey} onChange={(e) => setS3SecretAccessKey(e.target.value)} placeholder={SECRET_MASK} />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">{t("s3.endpointHint")}</p>
              </div>
            )}

            {isObjectStore && (
              <p className="text-xs text-muted-foreground">{t("restartHint")}</p>
            )}

            <div className="flex items-center gap-3">
              <Button onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {tCommon("save")}
              </Button>
              {saved && (
                <span className="flex items-center gap-1 text-sm text-green-600">
                  <CheckCircle2 className="h-4 w-4" />
                  {t("saved")}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
