"use client";

import { useEffect, useRef, useState } from "react";

import { assistantRequest } from "./assistant-api-client";
import { safeTermsUrl, type AssistantModel } from "./assistant-contract";
import {
  customProviderReviewIsValid,
  customProviderReviewTupleChanged,
  type CustomProviderReview,
} from "./assistant-custom-provider-contract";
import {
  readOpenCodeConsoleInventory,
  type OpenCodeConsoleInventory,
  type OpenCodeConsoleModel,
} from "./assistant-opencode-contract";
import { providerBaseUrlIsSecure, safeConfiguredBaseUrl } from "./assistant-provider-url";
import {
  nativeOAuthAvailabilityText,
  readNativeOAuthAttempts,
  readNativeOAuthConnections,
  readNativeOAuthMethods,
  safeNativeOAuthAuthorizationUrl,
  safePastedOAuthCallback,
  type NativeOAuthAttempt,
  type NativeOAuthConnection,
  type NativeOAuthMethod,
} from "./assistant-oauth-contract";
import styles from "./assistant-provider-settings.module.css";

type ProviderRow = {
  provider_id: string;
  display_name: string;
  auth_methods: string[];
  native_provider_id?: string | null;
  adapter_id?: string | null;
  protocol?: string | null;
  supported_auth_methods: string[];
  selected_model_id?: string | null;
  selected_base_url?: string | null;
  credential_required: boolean;
  credential_configured: boolean;
  oauth_connected: boolean;
  connection_status: string;
  endpoint_editable: boolean;
  credential_supported: boolean;
  validation_requires_credential: boolean;
  unsupported_reason?: string | null;
  terms_url?: string | null;
  selected_terms_url?: string | null;
  selected_privacy_disclosure?: string | null;
  selected_billing_disclosure?: string | null;
  selected_billing_class?: "unknown" | "free" | "paid" | null;
  selected_endpoint_policy_reviewed?: boolean;
};

type ProviderPayload = { providers?: ProviderRow[] };
type ModelPayload = { items?: AssistantModel[] };
type OAuthMethodsPayload = { methods?: unknown };
type OAuthAttemptsPayload = { attempts?: unknown };
type OAuthConnectionsPayload = { connections?: unknown };
type OAuthAttemptEnvelope = { attempt?: unknown };
type OAuthAttemptInput = { code: string; callbackUrl: string };
type OpenCodeReviewInput = {
  terms_url: string;
  privacy_disclosure: string;
  billing_disclosure: string;
  billing_class: "unknown" | "free" | "paid";
  training_policy: "unknown" | "no_training" | "training_possible";
  confidential_data_policy: "unknown" | "allowed" | "prohibited";
  endpoint_policy_reviewed: boolean;
};
type OpenCodeModelEnvelope = { model?: unknown };

const providerIdPattern = /^[a-z][a-z0-9_-]{0,79}$/;
const providerStatuses = new Set(["configured", "unconfigured", "ready", "unavailable", "invalid", "error", "connected", "pending", "validation_failed"]);
const emptyCustomReview: CustomProviderReview = {
  terms_url: "",
  privacy_disclosure: "",
  billing_disclosure: "",
  billing_class: "unknown",
  endpoint_policy_reviewed: false,
};
const emptyOpenCodeReview: OpenCodeReviewInput = {
  terms_url: "",
  privacy_disclosure: "",
  billing_disclosure: "",
  billing_class: "unknown",
  training_policy: "unknown",
  confidential_data_policy: "unknown",
  endpoint_policy_reviewed: false,
};

export function AssistantProviderSettings({
  freshVerified,
  onStepUpRejected,
}: Readonly<{ freshVerified: boolean; onStepUpRejected: () => void }>) {
  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [models, setModels] = useState<AssistantModel[]>([]);
  const [openCodeModels, setOpenCodeModels] = useState<OpenCodeConsoleModel[]>([]);
  const [openCodeUnsupportedCount, setOpenCodeUnsupportedCount] = useState(0);
  const [openCodeLoadState, setOpenCodeLoadState] = useState<"locked" | "loading" | "ready" | "needs_connection" | "error">("locked");
  const [openCodeReviews, setOpenCodeReviews] = useState<Record<string, OpenCodeReviewInput>>({});
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({});
  const [modelIds, setModelIds] = useState<Record<string, string>>({});
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [customReviews, setCustomReviews] = useState<Record<string, CustomProviderReview>>({});
  const [busyProvider, setBusyProvider] = useState<string | null>(null);
  const [busyModel, setBusyModel] = useState<string | null>(null);
  const [clearTarget, setClearTarget] = useState<string | null>(null);
  const [policyAcknowledgements, setPolicyAcknowledgements] = useState<Record<string, { privacyVersion: string | null; billingVersion: string | null }>>({});
  const [oauthMethods, setOAuthMethods] = useState<NativeOAuthMethod[]>([]);
  const [oauthAttempts, setOAuthAttempts] = useState<NativeOAuthAttempt[]>([]);
  const [oauthConnections, setOAuthConnections] = useState<NativeOAuthConnection[]>([]);
  const [oauthInputs, setOAuthInputs] = useState<Record<string, OAuthAttemptInput>>({});
  const [oauthBusy, setOAuthBusy] = useState<string | null>(null);
  const oauthPollInFlight = useRef(false);

  async function reloadOAuth() {
    const [methodPayload, attemptPayload, connectionPayload] = await Promise.all([
      assistantRequest<OAuthMethodsPayload>("/api/v1/assistant/providers/oauth/methods"),
      assistantRequest<OAuthAttemptsPayload>("/api/v1/assistant/providers/oauth/attempts"),
      assistantRequest<OAuthConnectionsPayload>("/api/v1/assistant/providers/oauth/connections"),
    ]);
    setOAuthMethods(readNativeOAuthMethods(methodPayload));
    setOAuthAttempts(readNativeOAuthAttempts(attemptPayload));
    setOAuthConnections(readNativeOAuthConnections(connectionPayload));
  }

  async function reloadOpenCodeModels(forceFormRefresh = false) {
    if (!freshVerified) {
      setOpenCodeLoadState("locked");
      setOpenCodeModels([]);
      setOpenCodeUnsupportedCount(0);
      return;
    }
    setOpenCodeLoadState("loading");
    try {
      const payload = await assistantRequest<OpenCodeConsoleInventory>("/api/v1/assistant/providers/opencode/models");
      const inventory = readOpenCodeConsoleInventory(payload);
      setOpenCodeModels(inventory.models);
      setOpenCodeUnsupportedCount(inventory.unsupported_model_count);
      setOpenCodeReviews((current) => {
        const next = { ...current };
        for (const model of inventory.models) {
          if (forceFormRefresh || !next[model.model_id]) {
            next[model.model_id] = {
              terms_url: model.terms_url ?? "",
              privacy_disclosure: model.privacy_disclosure ?? "",
              billing_disclosure: model.billing_disclosure ?? "",
              billing_class: model.billing_class,
              training_policy: model.training_policy,
              confidential_data_policy: model.confidential_data_policy,
              endpoint_policy_reviewed: model.reviewed,
            };
          }
        }
        return next;
      });
      setOpenCodeLoadState("ready");
    } catch (reason) {
      const candidate = reason as { status?: unknown };
      if (candidate?.status === 409) {
        setOpenCodeModels([]);
        setOpenCodeUnsupportedCount(0);
        setOpenCodeLoadState("needs_connection");
      } else {
        setOpenCodeLoadState("error");
        handleRequestError(reason, "This administrator's OpenCode model inventory could not be refreshed.");
      }
    }
  }

  async function reload() {
    setLoadState("loading");
    setError("");
    try {
      const [providerResult, modelResult] = await Promise.all([
        assistantRequest<ProviderPayload>("/api/v1/assistant/providers"),
        assistantRequest<ModelPayload>("/api/v1/assistant/models"),
        reloadOAuth(),
      ]);
      const rows = Array.isArray(providerResult.providers)
        ? providerResult.providers.flatMap((item) => {
          if (!item || !providerIdPattern.test(item.provider_id) || typeof item.display_name !== "string") return [];
          return [{
            ...item,
            display_name: item.display_name.slice(0, 120),
            auth_methods: Array.isArray(item.auth_methods) ? item.auth_methods.filter((method) => typeof method === "string" && /^[a-z][a-z0-9_-]{0,39}$/.test(method)).slice(0, 12) : [],
            native_provider_id: typeof item.native_provider_id === "string" ? item.native_provider_id.slice(0, 80) : null,
            adapter_id: typeof item.adapter_id === "string" ? item.adapter_id.slice(0, 100) : null,
            protocol: typeof item.protocol === "string" ? item.protocol.slice(0, 80) : null,
            supported_auth_methods: Array.isArray(item.supported_auth_methods) ? item.supported_auth_methods.filter((method) => typeof method === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(method)).slice(0, 8) : [],
            selected_model_id: typeof item.selected_model_id === "string" && item.selected_model_id.length <= 160 ? item.selected_model_id : null,
            selected_base_url: safeConfiguredBaseUrl(item.selected_base_url),
            credential_required: item.credential_required === true,
            credential_configured: item.credential_configured === true,
            oauth_connected: item.oauth_connected === true,
            connection_status: typeof item.connection_status === "string" && providerStatuses.has(item.connection_status) ? item.connection_status : "unavailable",
            endpoint_editable: item.endpoint_editable === true,
            credential_supported: item.credential_supported === true,
            validation_requires_credential: item.validation_requires_credential === true,
            unsupported_reason: typeof item.unsupported_reason === "string" ? item.unsupported_reason.slice(0, 180) : null,
            terms_url: safeTermsUrl(item.terms_url),
            selected_terms_url: safeTermsUrl(item.selected_terms_url),
            selected_privacy_disclosure: typeof item.selected_privacy_disclosure === "string" ? item.selected_privacy_disclosure.slice(0, 2000) : null,
            selected_billing_disclosure: typeof item.selected_billing_disclosure === "string" ? item.selected_billing_disclosure.slice(0, 2000) : null,
            selected_billing_class: ["unknown", "free", "paid"].includes(item.selected_billing_class ?? "") ? item.selected_billing_class : null,
            selected_endpoint_policy_reviewed: item.selected_endpoint_policy_reviewed === true,
          }];
        })
        : [];
      const catalog = Array.isArray(modelResult.items) ? modelResult.items.filter((item) => item && typeof item.id === "string") : [];
      setProviders(rows);
      setModels(catalog);
      setBaseUrls(Object.fromEntries(rows.map((provider) => [provider.provider_id, safeConfiguredBaseUrl(provider.selected_base_url)])));
      setModelIds(Object.fromEntries(rows.map((provider) => [provider.provider_id, provider.selected_model_id ?? ""])));
      setCustomReviews(Object.fromEntries(rows.filter((provider) => provider.provider_id === "custom").map((provider) => [provider.provider_id, {
        terms_url: provider.selected_terms_url ?? "",
        privacy_disclosure: provider.selected_privacy_disclosure ?? "",
        billing_disclosure: provider.selected_billing_disclosure ?? "",
        billing_class: provider.selected_billing_class ?? "unknown",
        endpoint_policy_reviewed: false,
      }])));
      setLoadState("ready");
    } catch {
      setLoadState("error");
      setError("Provider settings are unavailable for this administrator session.");
    }
  }

  useEffect(() => { void reload(); }, []);

  useEffect(() => {
    if (freshVerified) void reloadOpenCodeModels();
    else {
      setOpenCodeLoadState("locked");
      setOpenCodeModels([]);
    }
  }, [freshVerified]);

  useEffect(() => {
    const pending = oauthAttempts.filter((attempt) => attempt.status === "pending");
    if (!pending.length) return;
    let active = true;
    const timer = setInterval(() => {
      if (oauthPollInFlight.current) return;
      oauthPollInFlight.current = true;
      void Promise.all(pending.map(async (attempt) => {
        const payload = await assistantRequest<OAuthAttemptEnvelope>(
          `/api/v1/assistant/providers/oauth/attempts/${attempt.attempt_id}`,
        );
        return readNativeOAuthAttempts({ attempts: [payload.attempt] })[0] ?? null;
      })).then((updated) => {
        if (!active) return;
        const byId = new Map(updated.filter((item): item is NativeOAuthAttempt => item !== null)
          .map((item) => [item.attempt_id, item]));
        setOAuthAttempts((current) => current.map((item) => byId.get(item.attempt_id) ?? item));
      }).catch(() => {
        if (active) setError("Native provider authorization status is temporarily unavailable.");
      }).finally(() => {
        oauthPollInFlight.current = false;
      });
    }, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [oauthAttempts]);

  function handleRequestError(reason: unknown, fallback: string) {
    const candidate = reason as { status?: unknown };
    if (candidate?.status === 403) {
      onStepUpRejected();
      setError("Fresh authenticator verification is required. Verify again in the administrator section below.");
      return;
    }
    setError(fallback);
  }

  function requireFreshForOAuth(action: string): boolean {
    if (freshVerified) return true;
    setError(`Verify your authenticator in the administrator section before ${action}.`);
    onStepUpRejected();
    return false;
  }

  function attemptFromEnvelope(payload: OAuthAttemptEnvelope): NativeOAuthAttempt | null {
    return readNativeOAuthAttempts({ attempts: [payload.attempt] })[0] ?? null;
  }

  async function startNativeOAuth(method: NativeOAuthMethod) {
    if (!requireFreshForOAuth("starting provider sign-in")) return;
    const key = `${method.integration_id}/${method.method_id}`;
    setOAuthBusy(key);
    setError("");
    setNotice("");
    try {
      const payload = await assistantRequest<OAuthAttemptEnvelope>(
        "/api/v1/assistant/providers/oauth/attempts",
        {
          method: "POST",
          body: JSON.stringify({ provider_id: method.integration_id, method_id: method.method_id }),
        },
      );
      const attempt = attemptFromEnvelope(payload);
      if (!attempt || attempt.status !== "pending"
        || attempt.integration_id !== method.integration_id || attempt.method_id !== method.method_id) {
        throw new Error("oauth_attempt_invalid");
      }
      setOAuthAttempts((current) => [...current.filter((item) => item.attempt_id !== attempt.attempt_id), attempt]);
      setNotice(`${method.label} started in this administrator session. Follow the instructions here; do not paste codes into chat.`);
    } catch (reason) {
      handleRequestError(reason, "Provider sign-in could not be started.");
    } finally {
      setOAuthBusy(null);
    }
  }

  async function refreshNativeOAuthAttempt(attempt: NativeOAuthAttempt) {
    try {
      const payload = await assistantRequest<OAuthAttemptEnvelope>(
        `/api/v1/assistant/providers/oauth/attempts/${attempt.attempt_id}`,
      );
      const updated = attemptFromEnvelope(payload);
      if (updated) {
        setOAuthAttempts((current) => current.map((item) => item.attempt_id === updated.attempt_id ? updated : item));
      }
    } catch (reason) {
      handleRequestError(reason, "Provider sign-in status could not be refreshed.");
    }
  }

  async function submitNativeOAuthCallback(attempt: NativeOAuthAttempt) {
    const input = oauthInputs[attempt.attempt_id] ?? { code: "", callbackUrl: "" };
    if (!requireFreshForOAuth("submitting the provider callback")) return;
    if (!safePastedOAuthCallback(input.callbackUrl)) {
      setError("Paste the complete callback link from the exact native sign-in window. The link is checked locally and is never opened by this app.");
      return;
    }
    setOAuthBusy(attempt.attempt_id);
    setError("");
    try {
      const payload = await assistantRequest<OAuthAttemptEnvelope>(
        `/api/v1/assistant/providers/oauth/attempts/${attempt.attempt_id}/callback`,
        { method: "POST", body: JSON.stringify({ callback_url: input.callbackUrl }) },
      );
      const updated = attemptFromEnvelope(payload);
      if (!updated) throw new Error("oauth_attempt_invalid");
      setOAuthAttempts((current) => current.map((item) => item.attempt_id === updated.attempt_id ? updated : item));
      setOAuthInputs((current) => ({ ...current, [attempt.attempt_id]: { ...input, callbackUrl: "" } }));
      setNotice("The callback was submitted to the matching sign-in attempt. Wait for its status to update before saving the connection.");
    } catch (reason) {
      setOAuthInputs((current) => ({ ...current, [attempt.attempt_id]: { ...input, callbackUrl: "" } }));
      handleRequestError(reason, "The provider callback was rejected or the attempt expired.");
    } finally {
      setOAuthBusy(null);
    }
  }

  async function completeNativeOAuth(attempt: NativeOAuthAttempt) {
    const input = oauthInputs[attempt.attempt_id] ?? { code: "", callbackUrl: "" };
    if (!requireFreshForOAuth("saving this provider connection")) return;
    if (attempt.mode === "code" && !input.code.trim()) {
      setError("Enter the one-time authorization code in this secure provider form.");
      return;
    }
    setOAuthBusy(attempt.attempt_id);
    setError("");
    setNotice("");
    try {
      const payload = await assistantRequest<OAuthAttemptEnvelope>(
        `/api/v1/assistant/providers/oauth/attempts/${attempt.attempt_id}/complete`,
        { method: "POST", body: JSON.stringify(attempt.mode === "code" ? { code: input.code.trim() } : {}) },
      );
      const updated = attemptFromEnvelope(payload);
      if (!updated) throw new Error("oauth_attempt_invalid");
      setOAuthAttempts((current) => current.map((item) => item.attempt_id === updated.attempt_id ? updated : item));
      setOAuthInputs((current) => ({ ...current, [attempt.attempt_id]: { code: "", callbackUrl: "" } }));
      if (updated.status === "connected") {
        await reloadOAuth();
        if (attempt.integration_id === "opencode") {
          await reloadOpenCodeModels(true);
          setNotice("The OpenCode connection is stored encrypted and can load this account’s model catalog. Each model still needs administrator review, a supported provider credential, model approval, and user consent.");
        } else {
          setNotice("The provider connection was stored encrypted for this account. Review the exact model policy and user consent before model requests.");
        }
      } else {
        setNotice("The provider has not completed sign-in yet. Wait for the attempt status to update.");
      }
    } catch (reason) {
      setOAuthInputs((current) => ({ ...current, [attempt.attempt_id]: { code: "", callbackUrl: "" } }));
      handleRequestError(reason, "The provider handoff could not be stored.");
    } finally {
      setOAuthBusy(null);
    }
  }

  async function cancelNativeOAuth(attempt: NativeOAuthAttempt) {
    if (!requireFreshForOAuth("cancelling provider sign-in")) return;
    setOAuthBusy(attempt.attempt_id);
    setError("");
    try {
      const payload = await assistantRequest<OAuthAttemptEnvelope>(
        `/api/v1/assistant/providers/oauth/attempts/${attempt.attempt_id}`,
        { method: "DELETE" },
      );
      const updated = attemptFromEnvelope(payload);
      if (!updated || updated.status !== "cancelled") throw new Error("oauth_cancel_invalid");
      setOAuthAttempts((current) => current.map((item) => item.attempt_id === updated.attempt_id ? updated : item));
      setOAuthInputs((current) => {
        const next = { ...current };
        delete next[attempt.attempt_id];
        return next;
      });
      setNotice("The provider sign-in attempt was cancelled.");
    } catch (reason) {
      handleRequestError(reason, "The provider sign-in attempt could not be cancelled.");
    } finally {
      setOAuthBusy(null);
    }
  }

  async function removeNativeOAuthConnection(connection: NativeOAuthConnection) {
    if (!requireFreshForOAuth("removing a provider connection")) return;
    const key = `${connection.integration_id}/${connection.method_id}`;
    setOAuthBusy(key);
    setError("");
    setNotice("");
    try {
      await assistantRequest(
        `/api/v1/assistant/providers/oauth/connections/${connection.integration_id}/${connection.method_id}`,
        { method: "DELETE" },
      );
      await reloadOAuth();
      setNotice("The encrypted provider connection was removed. It was not available to model requests.");
    } catch (reason) {
      handleRequestError(reason, "The provider connection could not be removed.");
    } finally {
      setOAuthBusy(null);
    }
  }

  async function saveProvider(provider: ProviderRow) {
    const id = provider.provider_id;
    const baseUrl = (baseUrls[id] ?? "").trim();
    const credential = credentials[id] ?? "";
    const modelId = modelIds[id] ?? "";
    const review = customReviews[id] ?? emptyCustomReview;
    const customTupleChanged = id === "custom"
      ? customProviderReviewTupleChanged(baseUrl, review, provider)
      : false;
    if (!freshVerified) {
      setError("Verify your authenticator in the administrator section before saving provider settings.");
      onStepUpRejected();
      return;
    }
    if (provider.endpoint_editable && baseUrl && !providerBaseUrlIsSecure(baseUrl)) {
      setError("Use a compatible HTTPS provider URL. Credentials, local HTTP endpoints, and query strings are not accepted.");
      return;
    }
    if (id === "custom" && !customProviderReviewIsValid(baseUrl, review)) {
      setError("Review the HTTPS endpoint, public terms link, both bounded disclosures, billing class, and administrator review checkbox before saving.");
      return;
    }
    setBusyProvider(id);
    setError("");
    setNotice("");
    try {
      const customBody = id === "custom" ? {
        base_url: baseUrl.trim(),
        terms_url: review.terms_url.trim(),
        privacy_disclosure: review.privacy_disclosure,
        billing_disclosure: review.billing_disclosure,
        billing_class: review.billing_class,
        endpoint_policy_reviewed: true,
        ...(provider.credential_supported && credential ? { credential } : {}),
        ...(!customTupleChanged && modelId ? { model_id: modelId } : {}),
      } : {
        ...(modelId ? { model_id: modelId } : {}),
        ...(provider.endpoint_editable && baseUrl ? { base_url: baseUrl } : {}),
        ...(provider.credential_supported && credential ? { credential } : {}),
      };
      await assistantRequest(
        id === "custom"
          ? "/api/v1/assistant/providers/custom"
          : "/api/v1/assistant/providers/" + encodeURIComponent(id),
        { method: "PUT", body: JSON.stringify(customBody) },
      );
      setNotice(provider.display_name + " settings saved. Any credential input has been cleared.");
      setCredentials((current) => ({ ...current, [id]: "" }));
      setClearTarget(null);
      await reload();
    } catch (reason) {
      setCredentials((current) => ({ ...current, [id]: "" }));
      handleRequestError(reason, "Provider settings could not be saved.");
    } finally {
      setBusyProvider(null);
    }
  }

  async function clearProvider(provider: ProviderRow) {
    if (!freshVerified) {
      setError("Verify your authenticator in the administrator section before clearing provider settings.");
      onStepUpRejected();
      return;
    }
    setBusyProvider(provider.provider_id);
    setError("");
    setNotice("");
    try {
      await assistantRequest("/api/v1/assistant/providers/" + encodeURIComponent(provider.provider_id), { method: "DELETE" });
      setNotice(provider.display_name + " credentials and endpoint settings were cleared.");
      setCredentials((current) => ({ ...current, [provider.provider_id]: "" }));
      setClearTarget(null);
      await reload();
    } catch (reason) {
      handleRequestError(reason, "Provider settings could not be cleared.");
    } finally {
      setBusyProvider(null);
    }
  }

  async function validateProvider(provider: ProviderRow) {
    if (!freshVerified) {
      setError("Verify your authenticator in the administrator section before testing a provider.");
      onStepUpRejected();
      return;
    }
    setBusyProvider(provider.provider_id);
    setError("");
    setNotice("");
    try {
      await assistantRequest(
        "/api/v1/assistant/providers/" + encodeURIComponent(provider.provider_id) + "/validate",
        { method: "POST", body: JSON.stringify({}) },
      );
      setNotice(provider.display_name + ": Validation finished. Review the connection status above.");
      await reload();
    } catch (reason) {
      handleRequestError(reason, "The provider could not be validated.");
    } finally {
      setBusyProvider(null);
    }
  }

  async function updateModelPolicy(model: AssistantModel, enabled: boolean) {
    const modelId = model.model_id ?? model.id;
    const privacyVersion = model.privacy_policy_version ?? model.policy_version;
    const billingVersion = model.billing_policy_version ?? null;
    const acknowledgement = policyAcknowledgements[modelId] ?? { privacyVersion: null, billingVersion: null };
    if (!freshVerified) {
      setError("Verify your authenticator in the administrator section before changing model approval.");
      onStepUpRejected();
      return;
    }
    if (enabled && (acknowledgement.privacyVersion !== privacyVersion
      || !billingVersion
      || acknowledgement.billingVersion !== billingVersion
      || !model.cost_disclosure)) {
      setError("Review and acknowledge the current privacy and billing disclosures for this exact model before approving it.");
      return;
    }
    if (model.revision === undefined) {
      setError("This model has no current policy revision. Refresh before changing approval.");
      return;
    }
    setBusyModel(modelId);
    setError("");
    setNotice("");
    try {
      await assistantRequest(`/api/v1/assistant/models/${encodeURIComponent(modelId)}/policy`, {
        method: "PUT",
        body: JSON.stringify({
          enabled,
          acknowledged_privacy_policy_version: enabled ? privacyVersion : null,
          acknowledged_billing_policy_version: enabled ? billingVersion : null,
          expected_revision: model.revision,
        }),
      });
      setNotice(`${model.name} model approval ${enabled ? "enabled" : "disabled"}.`);
      setPolicyAcknowledgements((current) => ({ ...current, [modelId]: { privacyVersion: null, billingVersion: null } }));
      await reload();
      if ((model.provider_id ?? model.provider) === "opencode-console") {
        await reloadOpenCodeModels(true);
      }
    } catch (reason) {
      const candidate = reason as { status?: unknown };
      if (candidate?.status === 409) {
        await reload();
        if ((model.provider_id ?? model.provider) === "opencode-console") {
          await reloadOpenCodeModels(true);
        }
        setError("This model policy changed in another session. The current revision has been refreshed; review its disclosures before retrying.");
      } else {
        handleRequestError(reason, "The model approval could not be changed.");
      }
    } finally {
      setBusyModel(null);
    }
  }

  function editOpenCodeReview(modelId: string, changes: Partial<OpenCodeReviewInput>) {
    setOpenCodeReviews((current) => ({
      ...current,
      [modelId]: { ...(current[modelId] ?? emptyOpenCodeReview), ...changes },
    }));
  }

  async function saveOpenCodeReview(model: OpenCodeConsoleModel) {
    const review = openCodeReviews[model.model_id] ?? emptyOpenCodeReview;
    if (!freshVerified) {
      setError("Verify your authenticator in the administrator section before reviewing an OpenCode model.");
      onStepUpRejected();
      return;
    }
    if (!safeTermsUrl(review.terms_url) || !review.privacy_disclosure.trim()
      || !review.billing_disclosure.trim() || !review.endpoint_policy_reviewed) {
      setError("Review the public terms link, both administrator-provided statements, and the classifications for this exact model.");
      return;
    }
    setBusyModel(model.model_id);
    setError("");
    setNotice("");
    try {
      const payload = await assistantRequest<OpenCodeModelEnvelope>(
        `/api/v1/assistant/providers/opencode/models/${encodeURIComponent(model.model_id)}/review`,
        {
          method: "PUT",
          body: JSON.stringify({
            terms_url: review.terms_url.trim(),
            privacy_disclosure: review.privacy_disclosure,
            billing_disclosure: review.billing_disclosure,
            billing_class: review.billing_class,
            training_policy: review.training_policy,
            confidential_data_policy: review.confidential_data_policy,
            endpoint_policy_reviewed: true,
            expected_revision: model.review_revision,
            expected_config_fingerprint: model.config_fingerprint,
          }),
        },
      );
      const updated = readOpenCodeConsoleInventory({ models: [payload.model] }).models[0];
      if (!updated || updated.model_id !== model.model_id) throw new Error("opencode_model_review_invalid");
      setOpenCodeModels((current) => current.map((item) => item.model_id === updated.model_id ? updated : item));
      editOpenCodeReview(updated.model_id, {
        terms_url: updated.terms_url ?? "",
        privacy_disclosure: updated.privacy_disclosure ?? "",
        billing_disclosure: updated.billing_disclosure ?? "",
        billing_class: updated.billing_class,
        training_policy: updated.training_policy,
        confidential_data_policy: updated.confidential_data_policy,
        endpoint_policy_reviewed: updated.reviewed,
      });
      setPolicyAcknowledgements((current) => ({ ...current, [updated.model_id]: { privacyVersion: null, billingVersion: null } }));
      setNotice("Administrator-provided model review saved. These statements remain unverified; model approval requires fresh versioned privacy and billing acknowledgements.");
    } catch (reason) {
      const candidate = reason as { status?: unknown };
      if (candidate?.status === 409) {
        await reloadOpenCodeModels(true);
        setError("This Console model changed in another session. Its current endpoint and review revision were refreshed; inspect them before reviewing again.");
      } else {
        handleRequestError(reason, "The OpenCode model review could not be saved.");
      }
    } finally {
      setBusyModel(null);
    }
  }

  async function clearOpenCodeReview(model: OpenCodeConsoleModel) {
    if (!freshVerified) {
      setError("Verify your authenticator in the administrator section before clearing a model review.");
      onStepUpRejected();
      return;
    }
    setBusyModel(model.model_id);
    setError("");
    try {
      await assistantRequest(
        `/api/v1/assistant/providers/opencode/models/${encodeURIComponent(model.model_id)}/review?expected_revision=${model.review_revision}`,
        { method: "DELETE" },
      );
      setPolicyAcknowledgements((current) => ({ ...current, [model.model_id]: { privacyVersion: null, billingVersion: null } }));
      await reloadOpenCodeModels(true);
      setNotice("The model review was cleared. Existing approval no longer matches its current policy.");
    } catch (reason) {
      const candidate = reason as { status?: unknown };
      if (candidate?.status === 409) {
        await reloadOpenCodeModels(true);
        setError("This model review changed in another session. Its current review revision was refreshed.");
      } else {
        handleRequestError(reason, "The OpenCode model review could not be cleared.");
      }
    } finally {
      setBusyModel(null);
    }
  }

  function openCodePolicyModel(model: OpenCodeConsoleModel): AssistantModel {
    return {
      id: model.model_id,
      model_id: model.model_id,
      provider: "opencode-console",
      provider_id: "opencode-console",
      native_provider_id: model.protocol,
      name: model.display_name,
      availability: model.available ? "available" : "unavailable",
      available: model.available,
      enabled: model.enabled,
      usable: model.usable,
      free: model.billing_class === "free",
      training: model.training_policy,
      terms_url: model.terms_url,
      policy_version: model.privacy_policy_version ?? "",
      disclosure: model.privacy_disclosure ?? "",
      privacy_policy_version: model.privacy_policy_version ?? undefined,
      privacy_disclosure: model.privacy_disclosure ?? undefined,
      billing_class: model.billing_class,
      billing_policy_version: model.billing_policy_version,
      cost_disclosure: model.billing_disclosure,
      revision: model.revision,
      availability_reason: model.availability_reason,
    };
  }

  return (
    <section id="assistant-providers" tabIndex={-1} className={styles.section} aria-labelledby="assistant-providers-heading">
      <div className={styles.heading}>
        <div><p className="panel-kicker">Assistant / Administrator only</p><h2 id="assistant-providers-heading">Provider settings</h2></div>
        <button type="button" onClick={() => { void reload(); if (freshVerified) void reloadOpenCodeModels(true); }} disabled={loadState === "loading"}>Refresh</button>
      </div>
      <p className={styles.intro}>Credentials are entered here in a write-only secure form. They are never sent to the chat, shown again, or included in assistant context. Provider changes require a fresh authenticator check. Only compatible HTTPS endpoints are accepted; local HTTP proxy targets are managed by the application.</p>
      <section className={styles.customReview} aria-labelledby="assistant-native-oauth-heading">
        <div>
          <h3 id="assistant-native-oauth-heading">Native account connections</h3>
          <p role="note">Authorization codes and device instructions belong only in this administrator form. They are never added to chat or saved in browser storage. Model access follows the reviewed connection method, exact approved model policy, and each user’s consent.</p>
        </div>
        {oauthMethods.length === 0 ? <p role="status">No reviewed native sign-in methods are currently available.</p> : null}
        {oauthMethods.map((method) => {
          const key = `${method.integration_id}/${method.method_id}`;
          const connected = oauthConnections.some((item) => item.integration_id === method.integration_id && item.method_id === method.method_id);
          const activeAttempt = oauthAttempts.some((item) => item.integration_id === method.integration_id
            && item.method_id === method.method_id && ["pending", "handoff_ready"].includes(item.status));
          return <article className={styles.provider} key={key}>
            <div className={styles.providerHeader}>
              <div><h4>{method.label}</h4><p>{method.connection_status.replaceAll("_", " ")}</p></div>
              <span className={connected ? styles.configured : styles.notConfigured}>{connected ? "Connected" : "Not connected"}</span>
            </div>
            <p className={styles.methods}>{nativeOAuthAvailabilityText(method.availability_reason)}</p>
            <button type="button" onClick={() => void startNativeOAuth(method)}
              disabled={!freshVerified || oauthBusy !== null || connected || activeAttempt || !method.connection_supported}>
              {oauthBusy === key ? "Starting…" : `Connect ${method.label}`}
            </button>
          </article>;
        })}
        {oauthAttempts.map((attempt) => {
          const input = oauthInputs[attempt.attempt_id] ?? { code: "", callbackUrl: "" };
          const launchUrl = attempt.authorization_url
            && safeNativeOAuthAuthorizationUrl(attempt.integration_id, attempt.method_id, attempt.authorization_url)
            ? attempt.authorization_url : null;
          const active = attempt.status === "pending" || attempt.status === "handoff_ready";
          return <article className={styles.provider} key={attempt.attempt_id}>
            <div className={styles.providerHeader}>
              <div><h4>{attempt.integration_id} · {attempt.method_id.replaceAll("-", " ")}</h4>
                <p role="status">Sign-in status: {attempt.status.replaceAll("_", " ")}</p></div>
              <span className={active ? styles.notConfigured : styles.configured}>{active ? "In progress" : attempt.status}</span>
            </div>
            {attempt.instructions ? <p className={styles.methods}>{attempt.instructions}</p> : null}
            {launchUrl ? <p><a href={launchUrl} target="_blank" rel="noopener noreferrer">Open the provider sign-in page</a></p> : null}
            {attempt.status === "pending" && attempt.mode === "browser" ? <label htmlFor={`assistant-oauth-callback-${attempt.attempt_id}`}>
              Paste the complete callback link from the provider sign-in window (private administrator form)
              <input id={`assistant-oauth-callback-${attempt.attempt_id}`} type="url" inputMode="url" autoComplete="off" maxLength={4096}
                value={input.callbackUrl}
                onChange={(event) => setOAuthInputs((current) => ({ ...current, [attempt.attempt_id]: { ...input, callbackUrl: event.target.value } }))} />
            </label> : null}
            {attempt.status === "pending" && attempt.mode === "code" ? <label htmlFor={`assistant-oauth-code-${attempt.attempt_id}`}>
              One-time authorization code (private administrator form)
              <input id={`assistant-oauth-code-${attempt.attempt_id}`} type="password" autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={2048}
                value={input.code}
                onChange={(event) => setOAuthInputs((current) => ({ ...current, [attempt.attempt_id]: { ...input, code: event.target.value } }))} />
            </label> : null}
            <div className={styles.actions}>
              {attempt.status === "pending" && attempt.mode === "browser" ? <button type="button" onClick={() => void submitNativeOAuthCallback(attempt)} disabled={!freshVerified || oauthBusy !== null || !input.callbackUrl}>
                {oauthBusy === attempt.attempt_id ? "Submitting…" : "Submit callback link"}
              </button> : null}
              {attempt.status === "pending" && attempt.mode === "code" ? <button type="button" onClick={() => void completeNativeOAuth(attempt)} disabled={!freshVerified || oauthBusy !== null || !input.code.trim()}>
                {oauthBusy === attempt.attempt_id ? "Submitting…" : "Submit code"}
              </button> : null}
              {attempt.status === "handoff_ready" ? <button type="button" onClick={() => void completeNativeOAuth(attempt)} disabled={!freshVerified || oauthBusy !== null}>
                {oauthBusy === attempt.attempt_id ? "Saving…" : "Save encrypted connection"}
              </button> : null}
              {attempt.status === "pending" ? <button type="button" onClick={() => void refreshNativeOAuthAttempt(attempt)} disabled={oauthBusy !== null}>Refresh status</button> : null}
              {active ? <button type="button" className={styles.clearButton} onClick={() => void cancelNativeOAuth(attempt)} disabled={!freshVerified || oauthBusy !== null}>Cancel sign-in</button> : null}
            </div>
          </article>;
        })}
        {oauthConnections.map((connection) => {
          const key = `${connection.integration_id}/${connection.method_id}`;
          return <article className={styles.provider} key={`connection-${key}`}>
            <div className={styles.providerHeader}><div><h4>{connection.integration_id} · {connection.method_id.replaceAll("-", " ")}</h4><p>Encrypted app-side connection</p></div><span className={styles.configured}>Connected</span></div>
            <p className={styles.methods}>{nativeOAuthAvailabilityText(connection.availability_reason)}</p>
            <button type="button" className={styles.clearButton} onClick={() => void removeNativeOAuthConnection(connection)} disabled={!freshVerified || oauthBusy !== null}>
              {oauthBusy === key ? "Removing…" : "Remove encrypted connection"}
            </button>
          </article>;
        })}
      </section>
      <section className={styles.modelPolicies} aria-labelledby="assistant-opencode-models-heading">
        <div className={styles.providerHeader}>
          <div>
            <h3 id="assistant-opencode-models-heading">This administrator’s OpenCode model catalog</h3>
            <p>Fetched from the encrypted OpenCode connection for this account only. Refresh requires a fresh authenticator check.</p>
          </div>
          <button type="button" onClick={() => void reloadOpenCodeModels(true)} disabled={!freshVerified || openCodeLoadState === "loading"}>
            {openCodeLoadState === "loading" ? "Refreshing…" : "Refresh catalog"}
          </button>
        </div>
        {openCodeLoadState === "locked" ? <p role="status">Verify your authenticator to inspect this account’s private model catalog.</p> : null}
        {openCodeLoadState === "loading" ? <p role="status">Loading this account’s model catalog…</p> : null}
        {openCodeLoadState === "needs_connection" ? <p role="status">Connect the reviewed OpenCode device method above to load this account’s model configuration. The Console credential is used for catalog discovery; model requests use the separately stored provider credential shown below.</p> : null}
        {openCodeLoadState === "error" ? <p className={styles.error} role="status">The private catalog is unavailable. Check the connection and refresh.</p> : null}
        {openCodeLoadState === "ready" && openCodeUnsupportedCount > 0 ? <p role="note">{openCodeUnsupportedCount} model configuration entries use unsupported packages or settings and are not shown as usable.</p> : null}
        {openCodeLoadState === "ready" && openCodeModels.length === 0 ? <p role="status">No supported models are currently configured for this account.</p> : null}
        {openCodeModels.map((model) => {
          const review = openCodeReviews[model.model_id] ?? emptyOpenCodeReview;
          const privacyVersion = model.privacy_policy_version;
          const billingVersion = model.billing_policy_version;
          const acknowledgement = policyAcknowledgements[model.model_id] ?? { privacyVersion: null, billingVersion: null };
          const privacyAcknowledged = Boolean(privacyVersion && acknowledgement.privacyVersion === privacyVersion);
          const billingAcknowledged = Boolean(billingVersion && acknowledgement.billingVersion === billingVersion);
          const canEnable = privacyAcknowledged && billingAcknowledged && Boolean(model.billing_disclosure);
          const terms = safeTermsUrl(model.terms_url);
          const modelSuffix = model.model_id.slice(-12);
          const nativeModel = openCodePolicyModel(model);
          const billingLabel = model.billing_class === "free" ? "Admin assessed: free" : model.billing_class === "paid" ? "Admin assessed: paid" : "Billing unknown";
          const updateReview = (changes: Partial<OpenCodeReviewInput>) => editOpenCodeReview(model.model_id, {
            ...changes,
            ...("endpoint_policy_reviewed" in changes ? {} : { endpoint_policy_reviewed: false }),
          });
          return <article className={styles.modelPolicy} key={model.model_id}>
            <div className={styles.providerHeader}>
              <div>
                <h4>{model.display_name}</h4>
                <p>{model.protocol} · {billingLabel} · {model.usable ? "Usable" : model.availability_reason?.replaceAll("_", " ") ?? "Not approved"}</p>
              </div>
              <strong>{model.enabled ? "Enabled" : "Disabled"}</strong>
            </div>
            <p className={styles.methods}>Native model: <code>{model.native_model_id}</code></p>
            <p className={styles.methods}>Reviewed package: <code>{model.package_id}</code></p>
            <p className={styles.methods}>Exact HTTPS endpoint: <code>{model.endpoint}</code></p>
            <p role="note">All privacy, training, confidential-data, and billing statements below are supplied by the administrator and are unverified. Unknown billing/training policy or prohibited confidential-data use keeps this model unavailable. A Console OAuth token is not sent to model vendors; the adapter uses this app’s separately stored provider credential.</p>
            <label htmlFor={`assistant-opencode-terms-${modelSuffix}`}>Public provider terms URL
              <input id={`assistant-opencode-terms-${modelSuffix}`} type="url" inputMode="url" autoComplete="url" maxLength={2048}
                value={review.terms_url} onChange={(event) => updateReview({ terms_url: event.target.value })} />
            </label>
            <label htmlFor={`assistant-opencode-privacy-${modelSuffix}`}>Administrator-provided privacy and data-use statement (unverified)
              <textarea id={`assistant-opencode-privacy-${modelSuffix}`} maxLength={2000} rows={3} value={review.privacy_disclosure}
                onChange={(event) => updateReview({ privacy_disclosure: event.target.value })} />
            </label>
            <label htmlFor={`assistant-opencode-billing-${modelSuffix}`}>Administrator-provided billing statement (unverified)
              <textarea id={`assistant-opencode-billing-${modelSuffix}`} maxLength={2000} rows={3} value={review.billing_disclosure}
                onChange={(event) => updateReview({ billing_disclosure: event.target.value })} />
            </label>
            <label htmlFor={`assistant-opencode-billing-class-${modelSuffix}`}>Administrator billing assessment
              <select id={`assistant-opencode-billing-class-${modelSuffix}`} value={review.billing_class}
                onChange={(event) => updateReview({ billing_class: event.target.value as OpenCodeReviewInput["billing_class"] })}>
                <option value="unknown">Unknown</option>
                <option value="free">Free (administrator assessed)</option>
                <option value="paid">Paid (administrator assessed)</option>
              </select>
            </label>
            <label htmlFor={`assistant-opencode-training-${modelSuffix}`}>Administrator training/data-use assessment
              <select id={`assistant-opencode-training-${modelSuffix}`} value={review.training_policy}
                onChange={(event) => updateReview({ training_policy: event.target.value as OpenCodeReviewInput["training_policy"] })}>
                <option value="unknown">Unknown</option>
                <option value="no_training">No training (administrator statement, unverified)</option>
                <option value="training_possible">Training/data collection possible</option>
              </select>
            </label>
            <label htmlFor={`assistant-opencode-confidential-${modelSuffix}`}>Administrator confidential-data assessment
              <select id={`assistant-opencode-confidential-${modelSuffix}`} value={review.confidential_data_policy}
                onChange={(event) => updateReview({ confidential_data_policy: event.target.value as OpenCodeReviewInput["confidential_data_policy"] })}>
                <option value="unknown">Unknown</option>
                <option value="allowed">Allowed under current organization policy (administrator assessed)</option>
                <option value="prohibited">Prohibited</option>
              </select>
            </label>
            <label className={styles.policyAck}>
              <input type="checkbox" checked={review.endpoint_policy_reviewed}
                onChange={(event) => editOpenCodeReview(model.model_id, { endpoint_policy_reviewed: event.target.checked })} />
              I reviewed this exact endpoint, terms link, and administrator-provided statements.
            </label>
            <p className={styles.methods}>Configuration fingerprint {model.config_fingerprint} · Review revision {model.review_revision} · Model-policy revision {model.revision}</p>
            {terms ? <p><a href={terms} target="_blank" rel="noopener noreferrer">Open provider terms</a></p> : null}
            <div className={styles.actions}>
              <button type="button" onClick={() => void saveOpenCodeReview(model)} disabled={!freshVerified || busyModel !== null || !review.endpoint_policy_reviewed || !safeTermsUrl(review.terms_url) || !review.privacy_disclosure.trim() || !review.billing_disclosure.trim()}>
                {busyModel === model.model_id ? "Saving…" : model.reviewed ? "Update administrator review" : "Save administrator review"}
              </button>
              {model.reviewed ? <button type="button" className={styles.clearButton} onClick={() => void clearOpenCodeReview(model)} disabled={!freshVerified || busyModel !== null}>Clear review…</button> : null}
            </div>
            {model.reviewed ? <>
              <p>{model.privacy_disclosure}</p>
              <p>{model.billing_disclosure}</p>
              <p className={styles.methods}>Privacy policy {privacyVersion ?? "unavailable"} · Billing policy {billingVersion ?? "unavailable"} · {billingLabel}</p>
              <label className={styles.policyAck}><input type="checkbox" checked={privacyAcknowledged} disabled={!privacyVersion} onChange={(event) => setPolicyAcknowledgements((current) => ({ ...current, [model.model_id]: { ...acknowledgement, privacyVersion: event.target.checked ? privacyVersion : null } }))} /> I reviewed this exact model’s current privacy statement and policy version.</label>
              <label className={styles.policyAck}><input type="checkbox" checked={billingAcknowledged} disabled={!billingVersion || !model.billing_disclosure} onChange={(event) => setPolicyAcknowledgements((current) => ({ ...current, [model.model_id]: { ...acknowledgement, billingVersion: event.target.checked ? billingVersion : null } }))} /> I reviewed this exact model’s billing class and billing statement.</label>
              <div className={styles.actions}>
                {model.enabled && model.usable
                  ? <button type="button" className={styles.clearButton} onClick={() => void updateModelPolicy(nativeModel, false)} disabled={!freshVerified || busyModel !== null}>Disable this model</button>
                  : <button type="button" onClick={() => void updateModelPolicy(nativeModel, true)} disabled={!freshVerified || busyModel !== null || !canEnable || !model.available || !terms}>{model.enabled ? "Reapprove this model" : "Approve this model"}</button>}
              </div>
            </> : <p role="status">This model cannot be approved until its exact endpoint and administrator-reviewed terms and policies are saved.</p>}
          </article>;
        })}
      </section>
      {loadState === "loading" ? <p role="status">Loading provider status…</p> : null}
      {loadState === "error" ? <p className={styles.error} role="alert">{error}<button type="button" onClick={() => void reload()}>Retry</button></p> : null}
      {loadState === "ready" && providers.length === 0 ? <p>No provider settings are available.</p> : null}
      {providers.map((provider) => {
        const candidateModels = models.filter((model) => (model.provider_id ?? model.provider) === provider.provider_id);
        const activeModel = modelIds[provider.provider_id] ?? "";
        const currentCandidate = candidateModels.some((model) => model.id === activeModel);
        const providerId = provider.provider_id;
        const credential = credentials[providerId] ?? "";
        const review = customReviews[providerId] ?? emptyCustomReview;
        const customReviewValid = providerId === "custom"
          ? customProviderReviewIsValid(baseUrls[providerId] ?? "", review)
          : true;
        // Validation reads the provider's persisted connection, never the unsaved password field.
        const canValidate = provider.validation_requires_credential
          ? provider.credential_configured
          : provider.endpoint_editable
            ? Boolean(provider.selected_base_url)
            : true;
        return (
          <article className={styles.provider} key={providerId}>
            <div className={styles.providerHeader}>
              <div><h3>{provider.display_name}</h3><p>{provider.connection_status.replaceAll("_", " ")}</p></div>
              <span className={provider.credential_configured || provider.oauth_connected || provider.connection_status === "ready" ? styles.configured : styles.notConfigured}>
                {provider.oauth_connected ? "Connected" : provider.credential_configured ? "Credential stored" : provider.connection_status === "ready" ? "Ready" : provider.credential_supported ? provider.credential_required ? "Setup required" : "Credential optional" : "Provider managed"}
              </span>
            </div>
            <p className={styles.methods}>Authentication methods: {provider.supported_auth_methods.join(", ") || provider.auth_methods.join(", ") || "Provider-managed"}</p>
            {provider.terms_url && safeTermsUrl(provider.terms_url) ? <p><a href={safeTermsUrl(provider.terms_url)} target="_blank" rel="noopener noreferrer">Provider terms</a></p> : null}
            {providerId === "custom" && provider.selected_terms_url && provider.selected_terms_url === safeTermsUrl(provider.selected_terms_url)
              ? <p><a href={provider.selected_terms_url} target="_blank" rel="noopener noreferrer">Administrator-provided terms (unverified)</a></p>
              : null}
            <label htmlFor={"assistant-provider-model-" + providerId}>Provider default model
              <select id={"assistant-provider-model-" + providerId} value={activeModel} onChange={(event) => setModelIds((current) => ({ ...current, [providerId]: event.target.value }))}>
                <option value="">Keep provider default</option>
                {!currentCandidate && activeModel ? <option value={activeModel}>{activeModel} · Current selection</option> : null}
                {candidateModels.map((model) => {
                  const billingClass = model.billing_class ?? (model.free ? "free" : "paid");
                  const billingLabel = billingClass === "paid" ? "Paid" : billingClass === "free" ? "Free" : "Billing unknown";
                  return <option value={model.id} key={model.id} disabled={!model.usable}>{model.name} · {billingLabel} · {model.usable ? "Approved" : "Unavailable"}</option>;
                })}
              </select>
            </label>
            {provider.endpoint_editable ? <label htmlFor={"assistant-provider-url-" + providerId}>{providerId === "custom" ? "Compatible HTTPS endpoint" : "Provider endpoint (optional)"}
              <input id={"assistant-provider-url-" + providerId} type="url" inputMode="url" autoComplete="url" maxLength={2048} required={providerId === "custom"} value={baseUrls[providerId] ?? ""} onChange={(event) => setBaseUrls((current) => ({ ...current, [providerId]: event.target.value }))} placeholder="https://api.example.com" />
            </label> : provider.selected_base_url ? <p className={styles.methods}>Provider-managed endpoint: <code>{provider.selected_base_url}</code></p> : null}
            {provider.credential_supported ? <label htmlFor={"assistant-provider-secret-" + providerId}>New provider credential (write-only)
              <input id={"assistant-provider-secret-" + providerId} type="password" autoComplete="new-password" autoCapitalize="none" spellCheck={false} value={credential} onChange={(event) => setCredentials((current) => ({ ...current, [providerId]: event.target.value }))} placeholder={provider.credential_configured ? "Enter only to replace current credential" : "Enter provider credential"} />
            </label> : <p className={styles.methods}>This provider uses its supported native connection. No provider credential is requested here.</p>}
            {providerId === "custom" ? <div className={styles.customReview}>
              <p role="note">Custom endpoint statements are supplied by the administrator and are not independently verified. The app cannot confirm provider privacy, retention, training, or price from this form. “Unknown” billing is not treated as free.</p>
              <label htmlFor="assistant-custom-terms-url">Public provider terms URL
                <input id="assistant-custom-terms-url" type="url" inputMode="url" autoComplete="url" maxLength={2048} required value={review.terms_url} onChange={(event) => setCustomReviews((current) => ({ ...current, [providerId]: { ...review, terms_url: event.target.value, endpoint_policy_reviewed: false } }))} placeholder="https://provider.example/terms" />
              </label>
              <label htmlFor="assistant-custom-privacy-disclosure">Administrator-provided privacy disclosure (unverified)
                <textarea id="assistant-custom-privacy-disclosure" maxLength={2000} rows={3} value={review.privacy_disclosure} onChange={(event) => setCustomReviews((current) => ({ ...current, [providerId]: { ...review, privacy_disclosure: event.target.value, endpoint_policy_reviewed: false } }))} />
              </label>
              <label htmlFor="assistant-custom-billing-disclosure">Administrator-provided billing disclosure (unverified)
                <textarea id="assistant-custom-billing-disclosure" maxLength={2000} rows={3} value={review.billing_disclosure} onChange={(event) => setCustomReviews((current) => ({ ...current, [providerId]: { ...review, billing_disclosure: event.target.value, endpoint_policy_reviewed: false } }))} />
              </label>
              <label htmlFor="assistant-custom-billing-class">Administrator’s billing classification
                <select id="assistant-custom-billing-class" value={review.billing_class} onChange={(event) => setCustomReviews((current) => ({ ...current, [providerId]: { ...review, billing_class: event.target.value as CustomProviderReview["billing_class"], endpoint_policy_reviewed: false } }))}>
                  <option value="unknown">Unknown</option>
                  <option value="free">Free (administrator assessed)</option>
                  <option value="paid">Paid (administrator assessed)</option>
                </select>
              </label>
              <label className={styles.policyAck}>
                <input type="checkbox" checked={review.endpoint_policy_reviewed} onChange={(event) => setCustomReviews((current) => ({ ...current, [providerId]: { ...review, endpoint_policy_reviewed: event.target.checked } }))} />
                I reviewed this endpoint’s terms and administrator-provided statements.
              </label>
              <p className={styles.methods}>Text limits: 2,000 UTF-8 bytes per disclosure. Saving endpoint or policy changes clears the selected model and requires fresh model approval and user consent.</p>
            </div> : null}
            {provider.unsupported_reason ? <p className={styles.error} role="status">{provider.unsupported_reason.replaceAll("_", " ")}</p> : null}
            <p className={styles.stepup} role="note">{freshVerified ? "Fresh authenticator verified for this session." : "Use the authenticator control below before making changes."}</p>
            <div className={styles.actions}>
              {(provider.endpoint_editable || provider.credential_supported || Boolean(provider.selected_model_id) || Boolean(activeModel && activeModel !== provider.selected_model_id)) ? <button type="button" onClick={() => void saveProvider(provider)} disabled={!freshVerified || busyProvider !== null || !customReviewValid}>{busyProvider === providerId ? "Saving…" : "Save provider settings"}</button> : null}
              <button type="button" onClick={() => void validateProvider(provider)} disabled={!freshVerified || busyProvider !== null || !canValidate}>{busyProvider === providerId ? "Checking…" : "Validate provider"}</button>
              {clearTarget === providerId ? <div className={styles.clearConfirm}>
                <span>Clear the stored credential and endpoint?</span>
                <button type="button" onClick={() => void clearProvider(provider)} disabled={!freshVerified || busyProvider !== null}>Confirm clear</button>
                <button type="button" onClick={() => setClearTarget(null)}>Keep settings</button>
              </div> : <button type="button" className={styles.clearButton} onClick={() => setClearTarget(providerId)} disabled={!provider.credential_configured && !provider.selected_base_url && !provider.selected_model_id}>Clear provider settings…</button>}
            </div>
          </article>
        );
      })}
      {models.length ? <section className={styles.modelPolicies} aria-labelledby="assistant-model-policies-heading">
        <div><h3 id="assistant-model-policies-heading">Model approvals</h3><p>Approval applies to one exact model and policy version. Users still choose their own usable model for each conversation.</p></div>
        {models.map((model) => {
          const modelId = model.model_id ?? model.id;
          const privacyVersion = model.privacy_policy_version ?? model.policy_version;
          const billingVersion = model.billing_policy_version;
          const billingClass = model.billing_class ?? (model.free ? "free" : "paid");
          const billingLabel = billingClass === "paid" ? "Paid" : billingClass === "free" ? "Free" : "Billing unknown";
          const customProvider = (model.provider_id ?? model.provider) === "custom";
          const acknowledgements = policyAcknowledgements[modelId] ?? { privacyVersion: null, billingVersion: null };
          const privacyAcknowledged = Boolean(privacyVersion && acknowledgements.privacyVersion === privacyVersion);
          const billingAcknowledged = Boolean(billingVersion && acknowledgements.billingVersion === billingVersion);
          const canEnable = privacyAcknowledged
            && Boolean(billingVersion && billingAcknowledged && model.cost_disclosure);
          const terms = safeTermsUrl(model.terms_url);
          return <article className={styles.modelPolicy} key={modelId}>
            <div className={styles.providerHeader}><div><h4>{model.name}</h4><p>{model.provider_id ?? model.provider} · {billingLabel} · {model.usable ? "Usable" : model.availability_reason ?? "Not usable"}</p></div><strong>{model.enabled ? "Enabled" : "Disabled"}</strong></div>
            {customProvider ? <p role="note">The endpoint terms and disclosures were provided by an administrator and have not been independently verified. Billing remains unknown unless explicitly classified.</p> : null}
            <p>{model.privacy_disclosure ?? model.disclosure}</p>
            {model.cost_disclosure ? <p>{model.cost_disclosure}</p> : null}
            {terms ? <p><a href={terms} target="_blank" rel="noopener noreferrer">Review provider terms</a></p> : <p role="status">Provider terms link is unavailable.</p>}
            <p className={styles.methods}>Privacy policy {privacyVersion || "unavailable"} · Billing policy {billingVersion || "not applicable"} · Revision {model.revision ?? "unavailable"}</p>
            <label className={styles.policyAck}><input type="checkbox" checked={privacyAcknowledged} disabled={!privacyVersion} onChange={(event) => setPolicyAcknowledgements((current) => ({ ...current, [modelId]: { ...acknowledgements, privacyVersion: event.target.checked ? privacyVersion : null } }))} /> I reviewed this exact model’s privacy disclosure and version.</label>
            {billingVersion ? <label className={styles.policyAck}><input type="checkbox" checked={billingAcknowledged} disabled={!model.cost_disclosure} onChange={(event) => setPolicyAcknowledgements((current) => ({ ...current, [modelId]: { ...acknowledgements, billingVersion: event.target.checked ? billingVersion : null } }))} /> {billingClass === "paid" ? "I reviewed this exact model’s billing terms and cost disclosure." : billingClass === "free" ? "I reviewed this exact model’s free availability and billing disclosure." : "I reviewed this exact model’s billing disclosure; billing class is unknown."}</label> : null}
            <div className={styles.actions}>
              {model.enabled ? <button type="button" className={styles.clearButton} onClick={() => void updateModelPolicy(model, false)} disabled={!freshVerified || busyModel !== null}>{busyModel === modelId ? "Updating…" : "Disable this model"}</button>
                : <button type="button" onClick={() => void updateModelPolicy(model, true)} disabled={!freshVerified || busyModel !== null || !canEnable || !model.available || !terms}>{busyModel === modelId ? "Updating…" : "Approve this model"}</button>}
            </div>
          </article>;
        })}
      </section> : null}
      {error && loadState !== "error" ? <p className={styles.error} role="alert">{error}</p> : null}
      {notice ? <p className={styles.notice} role="status">{notice}</p> : null}
    </section>
  );
}
