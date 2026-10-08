import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  assistantContextRequest,
  assistantContextUrl,
  assistantHistoryDestination,
  assistantErrorMessage,
  assistantApiPath,
  assistantTurnContext,
  consumeAssistantStream,
  parseAssistantSseFrame,
  readAssistantBrowserAction,
  readPrivateWebFetchPreview,
  safeAssistantDestination,
  safeAssistantCitationUrl,
  safeTermsUrl,
} from "./assistant-contract.ts";
import { parseAssistantAnswer } from "./assistant-answer-model.ts";

test("provider controls share themed 44px targets and preserve destructive and forced-color overrides", async () => {
  const css = await readFile(new URL("./assistant-provider-settings.module.css", import.meta.url), "utf8");
  const base = css.match(/\.section button\{([^}]+)\}/)?.[1];
  assert.ok(base);
  for (const declaration of [
    "min-height:44px", "min-width:44px", "border:1px solid var(--accent)",
    "background:var(--accent)", "color:var(--panel)", "font:inherit",
  ]) assert.ok(base.split(";").includes(declaration), declaration);
  assert.ok(css.includes(".section button:disabled{opacity:.55;cursor:not-allowed}"));
  assert.ok(css.includes(".section .clearButton{border-color:var(--bad);background:var(--panel);color:var(--bad)}"));
  assert.ok(css.includes(".clearConfirm button:last-child{border-color:var(--border);background:var(--panel);color:var(--text)}"));
  const forcedColors = css.slice(css.indexOf("@media(forced-colors:active)"));
  assert.ok(forcedColors.includes(".section button,.section .clearButton,.clearConfirm button:last-child{border:1px solid ButtonText;background:ButtonFace;color:ButtonText}"));
});

test("assistant text and mobile composer retain readable whitespace and full-width controls", async () => {
  const css = await readFile(new URL("./assistant.module.css", import.meta.url), "utf8");
  const readiness = css.match(/\.readiness\{([^}]+)\}/)?.[1];
  assert.ok(readiness);
  for (const declaration of ["min-height:32px", "padding:.4rem .55rem", "font-size:.875rem", "line-height:1.35"]) {
    assert.ok(readiness.split(";").includes(declaration), declaration);
  }
  assert.doesNotMatch(readiness, /(?:^|;)font:inherit(?:;|$)/);

  const statusText = css.match(/\.readiness>span:nth-child\(2\)\{([^}]+)\}/)?.[1];
  assert.ok(statusText);
  for (const declaration of ["font:inherit", "padding-block:1px"]) {
    assert.ok(statusText.split(";").includes(declaration), declaration);
  }
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  const readinessRow = panel.slice(panel.indexOf("<div className={styles.readiness}"), panel.indexOf("</div>", panel.indexOf("<div className={styles.readiness}")));
  assert.match(readinessRow, /<span className=\{styles\.statusDot\}[^>]*\/>\s*<span>\{showWorkerReason\(status\)\}<\/span>/);
  assert.match(readinessRow, /status\?\.enabled && !workerReady \? <button type="button" className=\{styles\.textButton\}/);
  assert.match(readinessRow, /readinessChecking \? "Checking…" : "Check readiness"/);

  const answerParagraph = css.match(/\.answerBlocks>p\{([^}]+)\}/)?.[1];
  assert.ok(answerParagraph);
  assert.ok(answerParagraph.split(";").includes("white-space:pre-line"));
  const paragraphCode = css.match(/\.answerBlocks>p code\{([^}]+)\}/)?.[1];
  assert.ok(paragraphCode);
  assert.ok(paragraphCode.split(";").includes("white-space:pre-wrap"));
  assert.ok(css.includes(".answerBlocks strong{font-weight:780}"));
  assert.ok(css.includes(".answerBlocks ul,.answerBlocks ol{display:grid;gap:.2rem;margin:0;padding-left:1.3rem}"));
  const composerDisclaimer = css.match(/\.composerActions p\{([^}]+)\}/)?.[1];
  assert.ok(composerDisclaimer);
  assert.ok(composerDisclaimer.split(";").includes("padding-block:1px"));
  assert.doesNotMatch(css, /#assistant-disclaimer\s*\{/);

  const mobileStyles = css.slice(css.indexOf("@media(max-width:699px)"));
  assert.ok(mobileStyles.startsWith("@media(max-width:699px)"));
  const mobileReadiness = mobileStyles.match(/\.readiness\{([^}]+)\}/)?.[1];
  assert.ok(mobileReadiness);
  assert.ok(mobileReadiness.split(";").includes("font-size:.875rem"));
  assert.ok(mobileStyles.includes(".composerActions{align-items:stretch;flex-direction:column}"));
  assert.ok(mobileStyles.includes(".composerActions p{max-width:none}"));
  const mobileSend = mobileStyles.match(/\.composerActions button\{([^}]+)\}/)?.[1];
  assert.ok(mobileSend);
  for (const declaration of ["width:100%", "max-width:none", "min-height:44px"]) {
    assert.ok(mobileSend.split(";").includes(declaration), declaration);
  }
});

test("mobile assistant modal hides only its inert page underlay and restores the prior marker", async () => {
  const host = await readFile(new URL("./assistant-host.tsx", import.meta.url), "utf8");
  const layout = await readFile(new URL("../../app/layout.tsx", import.meta.url), "utf8");
  assert.match(layout, /<body>\s*<div data-assistant-background>\{children\}<\/div>\s*<AssistantHost\s*\/>\s*<\/body>/);

  const effectStart = host.indexOf("useLayoutEffect(() => {");
  const effectEnd = host.indexOf("\n  }, [isMobileViewport, open]);", effectStart);
  assert.ok(effectStart >= 0 && effectEnd > effectStart);
  assert.match(host, /\}, \[isMobileViewport, open\]\);/);
  const modalEffect = host.slice(effectStart, effectEnd);
  assert.match(modalEffect, /if \(!open \|\| !isMobileViewport\) return;/);
  assert.match(modalEffect, /document\.querySelector<HTMLElement>\("\[data-assistant-background\]"\)/);
  assert.match(modalEffect, /const underlayAttribute = "data-assistant-mobile-modal-underlay"/);
  assert.match(modalEffect, /const previousUnderlayValue = background\.getAttribute\(underlayAttribute\)/);
  assert.match(modalEffect, /background\.inert = true/);
  assert.match(modalEffect, /background\.setAttribute\(underlayAttribute, "hidden"\)/);
  assert.match(modalEffect, /background\.inert = wasInert/);
  assert.match(modalEffect, /if \(previousUnderlayValue === null\) \{\s*background\.removeAttribute\(underlayAttribute\);\s*\} else \{\s*background\.setAttribute\(underlayAttribute, previousUnderlayValue\);/);

  const css = await readFile(new URL("./assistant.module.css", import.meta.url), "utf8");
  const mobileStyles = css.slice(css.indexOf("@media(max-width:699px)"), css.indexOf("@media(prefers-reduced-motion"));
  const underlayRule = ":global([data-assistant-background][data-assistant-mobile-modal-underlay=\"hidden\"]){visibility:hidden}";
  assert.equal((css.match(/data-assistant-mobile-modal-underlay/g) ?? []).length, 1);
  assert.ok(mobileStyles.includes(underlayRule));
  assert.doesNotMatch(mobileStyles, /data-assistant-mobile-modal-underlay[^}]*\b(?:display|opacity|pointer-events)\s*:/);
  assert.match(css, /:global\(body\[data-assistant-open="true"\]\) \[data-assistant-background\]\{display:none!important\}/);
});

test("mobile local-control handoff releases the assistant modal before focusing a validated heading", async () => {
  const host = await readFile(new URL("./assistant-host.tsx", import.meta.url), "utf8");
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  const handoffStart = host.indexOf("function handoffToLocalControls(");
  const handoffEnd = host.indexOf("\n  if (hostState", handoffStart);
  const handoff = host.slice(handoffStart, handoffEnd);
  assert.ok(handoffStart >= 0 && handoffEnd > handoffStart);
  assert.match(handoff, /targetId: "notes-heading" \| "alerts-heading", expectedHref: string/);
  assert.match(handoff, /setOpen\(false\)/);
  assert.match(handoff, /requestAnimationFrame\(\(\) => \{\s*window\.requestAnimationFrame/);
  assert.match(handoff, /window\.location\.href !== expectedHref/);
  assert.match(handoff, /background\.inert/);
  assert.match(handoff, /data-assistant-mobile-modal-underlay/);
  assert.match(handoff, /document\.body\.dataset\.assistantOpen === "true"/);
  assert.match(handoff, /document\.querySelector\('\[data-testid="assistant-panel"\]'\)/);
  assert.match(handoff, /targetId === "notes-heading"[\s\S]*h2#notes-heading\[tabindex="-1"\][\s\S]*h2#alerts-heading\[tabindex="-1"\]/);
  assert.match(handoff, /!target\.isConnected[\s\S]*target\.getClientRects\(\)\.length === 0/);
  assert.doesNotMatch(handoff, /launcherRef/);
  assert.match(host, /function closePanel\(\) \{\s*setOpen\(false\);\s*window\.requestAnimationFrame\(\(\) => launcherRef\.current\?\.focus\(\)\);/);

  const actionStart = panel.indexOf("async function confirmAction(");
  const actionEnd = panel.indexOf("\n  async function confirmSearch", actionStart);
  const confirmAction = panel.slice(actionStart, actionEnd);
  const loadStart = panel.indexOf("async function loadConversation(");
  const loadEnd = panel.indexOf("\n  async function loadEarlierMessages", loadStart);
  const loadConversation = panel.slice(loadStart, loadEnd);
  assert.ok(actionStart >= 0 && actionEnd > actionStart);
  assert.ok(loadStart >= 0 && loadEnd > loadStart);
  assert.match(loadConversation, /Promise<number \| undefined>/);
  assert.match(loadConversation, /if \(generation !== conversationLoadGeneration\.current\) return;/);
  assert.match(loadConversation, /setConversationState\("error"\)[\s\S]*return;\s*}\s*return generation;/);
  assert.match(confirmAction, /localControlsHandoffTarget: "notes-heading" \| "alerts-heading" \| null/);
  const identityGuardStart = confirmAction.indexOf("if (!browserActionIdentityMatches(browserAction, instrument))");
  const identityBranchEnd = confirmAction.indexOf("} else if (result.browser_action !== undefined)", identityGuardStart);
  assert.ok(identityGuardStart >= 0 && identityBranchEnd > identityGuardStart);
  const identityBranch = confirmAction.slice(identityGuardStart, identityBranchEnd);
  const successfulHandoffGuard = identityBranch.indexOf("if (result.ok && isMobile && contextIsCurrent() && window.location.href === hrefAtStart)");
  assert.ok(successfulHandoffGuard > identityBranch.indexOf("if (!browserActionIdentityMatches(browserAction, instrument))"));
  assert.ok(identityBranch.indexOf('localControlsHandoffTarget = "notes-heading"') > successfulHandoffGuard);
  assert.ok(identityBranch.indexOf('localControlsHandoffTarget = "alerts-heading"') > successfulHandoffGuard);
  assert.match(identityBranch, /browserAction\.type === "notes\.set" \|\| browserAction\.type === "notes\.clear"[\s\S]*localControlsHandoffTarget = "notes-heading"/);
  assert.match(identityBranch, /browserAction\.type === "alerts\.remove"[\s\S]*localControlsHandoffTarget = "alerts-heading"/);
  assert.doesNotMatch(confirmAction.slice(0, identityGuardStart), /localControlsHandoffTarget = "(?:notes|alerts)-heading"/);
  assert.match(confirmAction, /localControlsHandoffReloadGeneration = reloadGeneration/);
  assert.match(confirmAction, /conversationLoadGeneration\.current === localControlsHandoffReloadGeneration/);
  assert.match(confirmAction, /selectedConversationId\.current === targetConversationId/);
  assert.match(confirmAction, /contextGeneration === contextRequestGeneration\.current/);
  assert.match(confirmAction, /routeAtStart === currentPath\(\) && window\.location\.href === hrefAtStart/);
  assert.ok(confirmAction.indexOf("await loadConversation(targetConversationId)") < confirmAction.indexOf("onLocalHandoff(localControlsHandoffTarget, hrefAtStart)"));
});

test("pending WebFetch approval uses the parent scroll area while saved transcripts keep their own scroll", async () => {
  const css = await readFile(new URL("./assistant.module.css", import.meta.url), "utf8");
  const body = css.match(/\.body\{([^}]+)\}/)?.[1];
  assert.ok(body);
  assert.ok(body.split(";").includes("overflow:auto"));

  const transcript = css.match(/\.transcript\{([^}]+)\}/)?.[1];
  assert.ok(transcript);
  assert.ok(transcript.split(";").includes("overflow:auto"));

  const approvalTranscript = css.match(/\.transcript\.transcriptWebFetchApproval\{([^}]+)\}/)?.[1];
  assert.ok(approvalTranscript);
  for (const declaration of ["flex:0 0 auto", "min-height:0", "overflow:visible"]) {
    assert.ok(approvalTranscript.split(";").includes(declaration), declaration);
  }

  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  assert.match(panel, /className=\{webFetchPreviews\.length > 0 \? `\$\{styles\.transcript\} \$\{styles\.transcriptWebFetchApproval\}` : styles\.transcript\}/);
  assert.match(panel, /\{webFetchPreviews\.map\(\(preview\) => <WebFetchPreviewCard/);
  assert.match(panel, /This complete URL, including every query parameter, will be sent/);
  assert.match(panel, /This approval applies only to the exact URL shown above/);
  assert.match(panel, /It expires \{readableTimestamp\(preview\.expires_at\)\}/);
  assert.match(panel, /Approve exact URL once/);
  assert.ok(css.includes(",.composerActions button,.cardActions button,.reconnect,.cancel,.actionCard button,.searchCard button{min-height:44px"));
});

test("WebFetch approval refreshes page context and removes a stale preview before confirmation", async () => {
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  const start = panel.indexOf("async function confirmWebFetch(");
  const end = panel.indexOf("\n  const modelTerms =", start);
  assert.ok(start >= 0 && end > start);
  const confirm = panel.slice(start, end);
  const refresh = confirm.indexOf("await latestConfirmationContext(requestAtStart)");
  const compare = confirm.indexOf("confirmationContext.context_version !== preview.context_version");
  const post = confirm.indexOf("const result = await assistantRequest", compare);
  const endpoint = confirm.indexOf("/webfetch-previews/", post);
  assert.ok(refresh >= 0 && compare > refresh && post > compare && endpoint > post);
  assert.match(confirm, /setWebFetchPreviews\(\(current\) => current\.filter\(\(item\) => item\.preview_id !== preview\.preview_id\)\)/);
  assert.match(confirm, /No URL was sent; ask again for a fresh preview/);
  assert.match(confirm, /confirmationContext \? \{ context: confirmationContext \} : \{\}/);
});

test("assistant readiness recovery is visible, bounded, and tied to the latest host status", async () => {
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  assert.match(panel, /readinessRemainingRef\.current = 6/);
  assert.match(panel, /setTimeout\(\(\) => \{ void refreshAssistantStatus\(\); \}, 5000\)/);
  assert.match(panel, /document\.addEventListener\("visibilitychange"/);
  assert.match(panel, /statusRef\.current = initialStatus/);
  assert.match(panel, /generation !== readinessGenerationRef\.current/);
  assert.match(panel, /if \(!pageVisible \|\| panelMinimized \|\| !current\?\.enabled/);
  assert.match(panel, /readinessControllerRef\.current\?\.abort\(\)/);
  assert.match(panel, /const refreshAssistantStatus = useCallback\(async \(startWindow = false, force = false\)/);
  assert.match(panel, /if \(workerIsReady\) \{\s*const workerError = workerRecoveryErrorRef\.current;\s*workerRecoveryErrorRef\.current = null;\s*if \(workerError\) clearOwnedPanelError\(workerError\);/);
  assert.match(panel, /\+\+modelLoadGenerationRef\.current/);
  assert.match(panel, /if \(generation !== modelLoadGenerationRef\.current\) return;/);
  assert.match(panel, /code === "assistant_worker_unavailable"/);
  assert.match(panel, /useLayoutEffect\(\(\) => \{\s*if \(consentPolicyKeyRef\.current === consentPolicyKey\)/);
  assert.equal(assistantErrorMessage(503, "assistant_worker_unavailable"), "The assistant worker is unavailable. Your workspace remains available.");
});

test("assistant context controls stay available during recovery and clear only context-owned errors", async () => {
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  const sectionStart = panel.indexOf('<section className={styles.context} aria-label="Workspace context">');
  const sectionEnd = panel.indexOf("</section>", sectionStart);
  assert.ok(sectionStart >= 0 && sectionEnd > sectionStart);
  const section = panel.slice(sectionStart, sectionEnd);
  const contextTop = section.indexOf('<div className={styles.contextTop}>');
  const controls = section.indexOf('<div className={styles.contextControlRow}>');
  const controlsEnd = section.indexOf("</div>", controls);
  const refresh = section.indexOf("styles.contextRefresh", contextTop);
  const preview = section.indexOf('<details ref={contextDetailsRef} className={styles.contextDetails}>', controls);
  const loading = section.indexOf('{contextState === "loading"');
  const error = section.indexOf('{contextState === "error"');
  const ready = section.indexOf('{contextState === "ready" && context ?');
  assert.ok(contextTop >= 0 && refresh > contextTop && refresh < controls && controlsEnd > controls && preview > controls && preview < controlsEnd);
  assert.ok(ready > controls && ready < controlsEnd && controlsEnd < loading && loading < error);
  const controlRow = section.slice(controls, controlsEnd);
  assert.match(controlRow, /aria-label="Share selected references"/);
  assert.match(controlRow, /<summary>Preview<\/summary>/);
  assert.doesNotMatch(controlRow, /contextRefresh/);
  assert.match(controlRow, /includeContextRef\.current = event\.target\.checked/);
  assert.match(controlRow, /contextRequestGeneration\.current \+= 1/);
  const contextTopRow = section.slice(contextTop, controls);
  assert.match(contextTopRow, /styles\.contextRefresh/);
  assert.match(contextTopRow, /aria-label="Refresh context preview"/);
  assert.match(contextTopRow, />Refresh preview<\/button>/);
  assert.equal((section.match(/aria-label="Refresh context preview"/g) ?? []).length, 1);

  const selectionStart = panel.indexOf("function selectedContextRequest(");
  const selectionEnd = panel.indexOf("\n}\n\nexport function AssistantPanel", selectionStart);
  assert.ok(selectionStart >= 0 && selectionEnd > selectionStart);
  assert.match(panel.slice(selectionStart, selectionEnd), /return includeSelectedReferences \? request : \{ route: request\.route \};/);

  assert.match(panel, /type PanelErrorState = Readonly<\{ message: string; owner: symbol \| null \}>/);
  const errorSetterStart = panel.indexOf("const setPanelError = useCallback(");
  const errorSetterEnd = panel.indexOf("const [busy, setBusy]", errorSetterStart);
  assert.ok(errorSetterStart >= 0 && errorSetterEnd > errorSetterStart);
  const errorSetter = panel.slice(errorSetterStart, errorSetterEnd);
  assert.match(errorSetter, /if \(typeof next !== "function"\) return \{ message: next, owner: null \}/);
  assert.match(errorSetter, /return message === current\.message \? current : \{ message, owner: null \}/);
  assert.match(panel, /const clearOwnedPanelError = useCallback\(\(owner: symbol\) => \{\s*setPanelErrorState\(\(current\) => current\.owner === owner \? \{ message: "", owner: null \} : current\);/);
  assert.match(panel, /const owner = Symbol\("assistant-context-error"\);\s*contextErrorRef\.current = owner;\s*setPanelErrorState\(\{ message, owner \}\)/);
  assert.match(panel, /const owner = Symbol\("assistant-worker-error"\);\s*workerRecoveryErrorRef\.current = owner;\s*setPrompt\(text\);\s*setPanelErrorState\(\{ message, owner \}\)/);
  assert.match(panel, /const owner = Symbol\("assistant-readiness-error"\);\s*readinessErrorRef\.current = owner;\s*setPanelErrorState\(\{ message, owner \}\)/);
  assert.match(panel, /if \(workerError\) clearOwnedPanelError\(workerError\)/);

  const reload = panel.slice(panel.indexOf("async function reloadContext()"), panel.indexOf("async function latestConfirmationContext", panel.indexOf("async function reloadContext()")));
  assert.match(reload, /const generation = \+\+contextRequestGeneration\.current/);
  assert.match(reload, /selectedContextRequest\(request, includeContextRef\.current\)/);
  assert.match(reload, /clearContextError\(\)/);
  assert.match(reload, /reportContextError\(error\)/);
  const contextEffectStart = panel.indexOf("useEffect(() => {\n    let current = true;\n    const generation = ++contextRequestGeneration.current;");
  const contextEffectEnd = panel.indexOf("function handlePanelKeyDown", contextEffectStart);
  assert.ok(contextEffectStart >= 0 && contextEffectEnd > contextEffectStart);
  const contextEffect = panel.slice(contextEffectStart, contextEffectEnd);
  assert.match(contextEffect, /selectedContextRequest\(contextRequest, includeContextRef\.current\)/);
  assert.match(contextEffect, /if \(!current \|\| generation !== contextRequestGeneration\.current\) return;/);
  assert.match(contextEffect, /clearContextError\(\)/);
  assert.match(contextEffect, /reportContextError\(error\)/);
  assert.match(panel, /const clearContextError = useCallback\(\(\) => \{\s*const contextError = contextErrorRef\.current;\s*contextErrorRef\.current = null;\s*if \(contextError\) clearOwnedPanelError\(contextError\);/);
  assert.match(panel, /function selectedContextRequest\(request: AssistantContextRequest, includeSelectedReferences: boolean\)/);
  assert.match(panel, /if \(!current \|\| generation !== contextRequestGeneration\.current\) return;/);
});

test("print shows the nested saved context preview and hides its sharing controls", async () => {
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  const styles = await readFile(new URL("./assistant.module.css", import.meta.url), "utf8");
  const controlRow = panel.indexOf('<div className={styles.contextControlRow}>');
  const details = panel.indexOf('<details ref={contextDetailsRef} className={styles.contextDetails}>', controlRow);
  const controlRowEnd = panel.indexOf("\n            </div>\n            {contextState === \"loading\"", details);
  const printStart = styles.indexOf("@media print{");
  assert.ok(controlRow >= 0 && details > controlRow && controlRowEnd > details);
  assert.ok(printStart >= 0);

  const printStyles = styles.slice(printStart);
  const rowRules = printStyles.match(/\.contextControlRow\{([^}]*)\}/)?.[1] ?? "";
  assert.match(rowRules, /display:block!important/);
  assert.match(printStyles, /\.contextToggle/);
  assert.match(printStyles, /\.contextShareMode/);
  assert.match(printStyles, /\.contextDetails summary\{display:none!important\}/);
  assert.match(printStyles, /\.contextDetails \.contextPreview\{display:block!important/);
  assert.match(printStyles, /\.contextNote\{display:none!important\}/);
});

test("assistant policy changes clear consent acknowledgements and reload without resending the prompt", async () => {
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  assert.match(panel, /selectedModel\.policy_version,/);
  assert.match(panel, /selectedModel\.privacy_policy_version \?\? selectedModel\.policy_version,/);
  assert.match(panel, /selectedModel\.billing_policy_version \?\? null,/);
  assert.match(panel, /async function reloadAfterPolicyChange\(error: unknown, turnWasStarted = false\)/);
  const recovery = panel.slice(panel.indexOf("async function reloadAfterPolicyChange"), panel.indexOf("useEffect(() => {", panel.indexOf("async function reloadAfterPolicyChange")));
  assert.match(recovery, /setAcceptTerms\(false\)/);
  assert.match(recovery, /setAllowCollection\(false\)/);
  assert.match(recovery, /await loadModels\(\)/);
  assert.match(panel, /if \(code === "policy_version" \|\| code === "provider_policy_changed"\) \{\s*setPrompt\(text\);\s*await reloadAfterPolicyChange\(error\);/);
  assert.match(panel, /No assistant turn was started\. Review the current model terms before continuing\./);
  assert.match(panel, /The assistant turn stopped because its model policy changed\. Review the current terms before continuing\./);
  assert.match(panel, /event\.code === "assistant_worker_unavailable"/);
});

test("assistant live status has one persistent live announcer", async () => {
  const source = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  const liveStatusElements = Array.from(source.matchAll(
    /<(?<tag>[A-Za-z][A-Za-z0-9.]*)\b(?<attributes>[^>]*)>\{liveStatus\}<\/\k<tag>>/g,
  ));
  assert.equal(liveStatusElements.length, 2);

  const liveAnnouncers = liveStatusElements.filter(([, , attributes]) => /\baria-live=/.test(attributes));
  assert.equal(liveAnnouncers.length, 1);
  assert.equal(liveAnnouncers[0][1], "span");
  assert.match(liveAnnouncers[0][2], /className="sr-only"/);

  const visibleStatus = liveStatusElements.find(([, , attributes]) => /className=\{styles\.liveStatus\}/.test(attributes));
  assert.ok(visibleStatus);
  assert.doesNotMatch(visibleStatus[2], /\brole=|\baria-live=/);
  assert.match(source, /<p className=\{styles\.minimizedStatus\} role="status">\{busyTurn \? /);
});

test("route context accepts only page names and bounded normalized workspace identity", () => {
  assert.deepEqual(assistantContextRequest({
    pathname: "/tools/forecast",
    search: "?symbol=spy&asset_type=etf&provider=yahoo&exchange=arca&display_name=Private+label&event_id=42&result_id=7&invite_code=do-not-forward",
  }), {
    route: "/tools/forecast",
    symbol: "SPY",
    asset_type: "etf",
    provider: "yahoo",
    exchange: "arca",
    event_id: 42,
    result_id: 7,
  });
  assert.deepEqual(assistantContextRequest({
    pathname: "/tools/markets",
    search: "?symbol=brk-b&asset_type=stock&provider=Yahoo+Finance&exchange=NYSE",
  }), {
    route: "/tools/markets",
    symbol: "BRK-B",
    asset_type: "stock",
    provider: "Yahoo Finance",
    exchange: "NYSE",
  });
  assert.deepEqual(assistantContextRequest({
    pathname: "/admin",
    search: "?symbol=SPY&asset_type=etf&provider=yahoo&exchange=ARCA&invite_code=private",
  }), { route: "/admin" });
  assert.deepEqual(assistantContextRequest({
    pathname: "/account",
    search: "?symbol=SPY&asset_type=etf&provider=yahoo&exchange=ARCA",
  }), { route: "/account" });
  assert.equal(assistantContextRequest({ pathname: "/invite", search: "?code=private" }), null);
  assert.equal(assistantContextRequest({ pathname: "/authenticator", search: "?token=private" }), null);
  assert.equal(assistantContextRequest({ pathname: "/unknown", search: "?symbol=SPY" }), null);
});

test("instrument and saved-reference URL assertions are bounded and never carry display names", () => {
  const request = assistantContextRequest({
    pathname: "/research",
    search: "?symbol=SHOP.TO&asset_type=stock&provider=yahoo&exchange=TORONTO&display_name=anything&event_id=8&result_id=9",
  });
  assert.ok(request);
  assert.equal(request.symbol, "SHOP.TO");
  const url = assistantContextUrl(request);
  const parsed = new URL(url, "http://localhost");
  assert.equal(parsed.pathname, "/api/v1/assistant/context");
  assert.deepEqual(Object.fromEntries(parsed.searchParams), {
    route: "/research",
    symbol: "SHOP.TO",
    asset_type: "stock",
    provider: "yahoo",
    exchange: "TORONTO",
    event_id: "8",
    result_id: "9",
  });
  assert.equal(url.includes("display_name"), false);
  assert.equal(url.includes("anything"), false);

  assert.deepEqual(assistantContextRequest({
    pathname: "/overview",
    search: "?symbol=SPY&asset_type=etf&provider=yahoo&exchange=ARCA&event_id=8&result_id=9",
  }), {
    route: "/overview",
    symbol: "SPY",
    asset_type: "etf",
    provider: "yahoo",
    exchange: "ARCA",
  });
  assert.deepEqual(assistantContextRequest({
    pathname: "/tools/forecast",
    search: "?symbol=THIS_SYMBOL_IS_TOO_LONG&asset_type=stock&provider=yahoo&exchange=NYSE",
  }), { route: "/tools/forecast" });
  assert.deepEqual(assistantContextRequest({
    pathname: "/tools/forecast",
    search: "?symbol=SPY&asset_type=etf&provider=https%3A%2F%2Fexample.test&exchange=ARCA",
  }), { route: "/tools/forecast" });
});

test("typed browser bridge validates normalized actions and same-origin destinations", () => {
  assert.deepEqual(readAssistantBrowserAction({ type: "theme.set", payload: { theme: "system" } }, "/admin"), {
    type: "theme.set", payload: { theme: "system" },
  });
  assert.deepEqual(readAssistantBrowserAction({
    type: "filters.apply", payload: { query: "SPY", symbol: "", asset_type: "etf", status: "successful" },
  }, "/"), {
    type: "filters.apply", payload: { query: "SPY", asset_type: "etf", status: "successful" },
  });
  assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "SPY" } }, "/research"), null);
  assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", status: "pending" } }, "/"), null);
  assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", raw_url: "/admin" } }, "/"), null);
  assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x" }, owner_id: 7 }, "/"), null);
  assert.deepEqual(readAssistantBrowserAction({
    type: "notes.set", payload: { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", untrusted_note: "must not be echoed" },
  }, "/tools/live-trading"), {
    type: "notes.set", payload: { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA" },
  });
  assert.deepEqual(readAssistantBrowserAction({
    type: "alerts.add", payload: { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", threshold: 123.45 },
  }, "/tools/live-trading"), {
    type: "alerts.add", payload: { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", threshold: 123.45 },
  });
  assert.equal(readAssistantBrowserAction({
    type: "alerts.remove", payload: { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", index: 5 },
  }, "/tools/live-trading")?.type, "alerts.remove");
  assert.equal(safeAssistantDestination("//evil.test/"), undefined);
  assert.equal(safeAssistantDestination("/tools/markets?symbol=SPY&asset_type=etf&provider=Yahoo+Finance&exchange=ARCA&display_name=Private"), undefined);
  assert.equal(safeAssistantDestination("/tools/markets?symbol=SPY&asset_type=etf&provider=Yahoo+Finance&exchange=ARCA"), "/tools/markets?symbol=SPY&asset_type=etf&provider=Yahoo+Finance&exchange=ARCA");
  assert.equal(safeAssistantDestination("/?event_id=17#result-section"), "/?event_id=17#result-section");
  assert.equal(safeAssistantDestination("/?q=SPY&status=successful&asset_type=etf#history-heading"), "/?q=SPY&status=successful&asset_type=etf#history-heading");
  assert.equal(safeAssistantDestination("/?symbol=spy#history-heading"), undefined);
  assert.equal(safeAssistantDestination("/?q=SPY&symbol=SPY#history-heading"), undefined);
  assert.equal(safeAssistantDestination("/?q=x&analysis_kind=submitted_forecast&submitted_from=2026-01-01&submitted_to=2026-01-31&model=empirical&horizon=weekly_5&sort=symbol%3Aasc&page_size=50#history-heading"), "/?q=x&analysis_kind=submitted_forecast&submitted_from=2026-01-01&submitted_to=2026-01-31&model=empirical&horizon=weekly_5&sort=symbol%3Aasc&page_size=50#history-heading");
  assert.equal(safeAssistantDestination("/?q=x&unknown=y#history-heading"), undefined);
  assert.equal(safeAssistantDestination("/?submitted_from=2026-02-01&submitted_to=2026-01-01#history-heading"), undefined);
  assert.equal(safeAssistantDestination("/?submitted_from=2026-02-30#history-heading"), undefined);
  assert.equal(safeAssistantDestination("/?page_size=25#history-heading"), undefined);
  assert.equal(safeAssistantDestination("/?q=x&q=y#history-heading"), undefined);
  assert.equal(safeAssistantDestination("/api/v1/history-export.csv?target=https://evil.test"), undefined);
  assert.equal(safeAssistantDestination("/api/v1/history-export.csv"), undefined);
  const exportUrl = "/api/v1/history-export.csv?q=ACDC&status=successful&asset_type=etf&analysis_kind=submitted_forecast&submitted_from=2026-01-01T00%3A00%3A00Z&submitted_to=2026-01-31T23%3A59%3A59.999Z&model=empirical&horizon=weekly_5&sort_by=symbol&sort_order=asc";
  assert.equal(safeAssistantDestination(exportUrl), exportUrl);
  assert.equal(safeAssistantDestination("/api/v1/history-export.csv?symbol=SPY&sort_by=symbol&sort_order=asc"), "/api/v1/history-export.csv?symbol=SPY&sort_by=symbol&sort_order=asc");
  assert.equal(safeAssistantDestination(`${exportUrl}&page_size=10`), undefined);
  assert.equal(safeAssistantDestination("/api/v1/history-export.json?q=ACDC&sort_by=symbol&sort_order=asc&target=secret"), undefined);
  assert.equal(safeAssistantDestination("/api/v1/history-export.json?q=ACDC&sort_by=symbol&sort_order=asc&submitted_from=2026-01-01T01%3A00%3A00Z"), undefined);
});

test("history browser action accepts every supported filter and rejects malformed, stale, or forged values", () => {
  const payload = {
    query: "  ACDC  ", asset_type: "etf", status: "failed",
    analysis_kind: "fresh_historical_reconstruction", submitted_from: "2026-01-01", submitted_to: "2026-01-31",
    model: "empirical", horizon: "weekly_5", sort: "company:asc", page_size: 50,
  };
  assert.deepEqual(readAssistantBrowserAction({ type: "filters.apply", payload }, "/"), {
    type: "filters.apply", payload: { ...payload, query: "ACDC" },
  });
  for (const status of ["successful", "repeated", "failed"]) {
    assert.ok(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", status } }, "/"));
  }
  for (const asset_type of ["stock", "etf"]) {
    assert.ok(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", asset_type } }, "/"));
  }
  for (const analysis_kind of ["submitted_forecast", "fresh_historical_reconstruction"]) {
    assert.ok(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", analysis_kind } }, "/"));
  }
  for (const horizon of ["close_to_close", "completed_5m_to_close", "five_min_forward", "daily_1", "weekly_5", "monthly_21", "quarterly_63"]) {
    assert.ok(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", horizon } }, "/"));
  }
  for (const sort of ["event_id:desc", "event_id:asc", "symbol:asc", "company:asc", "status:asc"]) {
    assert.ok(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", sort } }, "/"));
  }
  for (const page_size of [10, 20, 50]) {
    assert.ok(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x", page_size } }, "/"));
  }
  assert.deepEqual(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "SPY", symbol: "" } }, "/"), {
    type: "filters.apply", payload: { query: "SPY" },
  });
  assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "SPY", symbol: "SPY" } }, "/"), null);
  assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "Apple", symbol: "AAPL" } }, "/"), null);
  const serverAction = {
    type: "filters.apply",
    payload: {
      query: "", asset_type: "", status: "", analysis_kind: "", submitted_from: "", submitted_to: "",
      model: "", horizon: "", sort: "event_id:desc", page_size: 10,
    },
    destination: { kind: "current-page", route: "/" },
  };
  assert.deepEqual(readAssistantBrowserAction(serverAction, "/"), {
    type: "filters.apply", payload: { query: "", sort: "event_id:desc", page_size: 10 },
  });
  assert.equal(readAssistantBrowserAction({ ...serverAction, destination: { kind: "current-page", route: "/tools/markets" } }, "/"), null);
  assert.equal(readAssistantBrowserAction({ ...serverAction, destination: { kind: "current-page", route: "/", target: "/admin" } }, "/"), null);
  for (const forged of [
    { query: "x", page_size: "10" },
    { query: "x", page_size: 25 },
    { query: "x", symbol: "INVALID SYMBOL" },
    { query: "x".repeat(31) },
    { query: "x", submitted_from: "2026-02-30" },
    { query: "x", submitted_to: "2026-01-01", submitted_from: "2026-01-02" },
    { query: "x", model: "m".repeat(121) },
    { query: "x", horizon: "daily" },
    { query: "x", sort: "model:desc" },
    { query: "x", debug: true },
  ]) assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: forged }, "/"), null);
  assert.equal(readAssistantBrowserAction({ type: "filters.apply", payload: { query: "x" } }, "/tools/markets"), null);
  assert.equal(assistantHistoryDestination(readAssistantBrowserAction({ type: "filters.apply", payload }, "/").payload), "/?q=ACDC&asset_type=etf&status=failed&analysis_kind=fresh_historical_reconstruction&submitted_from=2026-01-01&submitted_to=2026-01-31&model=empirical&horizon=weekly_5&sort=company%3Aasc&page_size=50#history-heading");
});

test("history handoff binds the complete existing form and preserves UTC calendar-day bounds", async () => {
  const page = await readFile(new URL("../../app/page.tsx", import.meta.url), "utf8");
  const app = await readFile(new URL("../../../src/stock_probs/static/app.js", import.meta.url), "utf8");
  for (const name of ["q", "status", "asset_type", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort", "page_size"]) {
    assert.ok(page.includes(`name=\"${name}\"`), `missing native history control ${name}`);
  }
  for (const field of ["analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort", "page_size"]) {
    assert.ok(app.includes(`\"${field}\"`), `history handoff does not validate ${field}`);
  }
  assert.ok(app.includes("`${values.get(\"submitted_from\")}T00:00:00Z`"));
  assert.ok(app.includes("`${values.get(\"submitted_to\")}T23:59:59.999Z`"));
  assert.ok(app.includes('sort: values.sort || "event_id:desc", page_size: values.page_size || "10"'));
  const initializerStart = app.indexOf("function initializeAssistantHistoryFilters()");
  const initializerEnd = app.indexOf("\nasync function initialize()", initializerStart);
  assert.ok(initializerStart >= 0 && initializerEnd > initializerStart);
  const initializer = app.slice(initializerStart, initializerEnd);
  assert.ok(initializer.includes('new Set(["q", "status", "asset_type", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort", "page_size"])'));
  assert.doesNotMatch(initializer, /values\.symbol/);
  assert.ok(app.includes("const exportParams = new URLSearchParams(params)"));
  assert.ok(app.includes("exportParams.delete(\"page_size\")"));
});

test("Markets browser actions validate every route-scoped option and reject forged numeric ranges", () => {
  const base = {
    query: "ACDC", exchange: "NASDAQ", asset_type: "etf", sort: "symbol:asc",
    min_price: "", max_price: "", min_change: "", max_change: "", min_volume: "",
    quote_field: "", quote_min: "", quote_max: "",
  };
  const parse = (type, payload) => readAssistantBrowserAction({ type, payload }, "/tools/markets");
  assert.deepEqual(parse("market.filters.apply", base), { type: "market.filters.apply", payload: base });
  for (const sort of ["symbol:asc", "symbol:desc", "price:desc", "price:asc", "change:desc", "volume:desc", "open:desc", "high:desc", "low:desc", "last:desc", "previous_close:desc", "last_trade:desc"]) {
    assert.ok(parse("market.filters.apply", { ...base, sort }));
  }
  for (const asset_type of ["", "stock", "etf"]) {
    assert.ok(parse("market.filters.apply", { ...base, asset_type }));
  }
  for (const quote_field of ["change_percent", "volume", "open", "high", "low", "last", "previous_close", "last_trade"]) {
    assert.ok(parse("market.filters.apply", { ...base, quote_field, quote_min: quote_field === "change_percent" ? "-10" : "0", quote_max: "10" }));
  }
  assert.ok(parse("market.filters.apply", { ...base, min_change: "-5", max_change: "-1" }));
  for (const forged of [
    { ...base, min_price: "NaN" },
    { ...base, min_price: "Infinity" },
    { ...base, min_price: "-0.01" },
    { ...base, min_price: "10", max_price: "9" },
    { ...base, min_change: "3", max_change: "-3" },
    { ...base, min_volume: "-1" },
    { ...base, min_volume: "1.5" },
    { ...base, quote_field: "volume", quote_min: "1.5" },
    { ...base, quote_field: "", quote_min: "1" },
    { ...base, quote_field: "open", quote_min: "-1" },
    { ...base, surprise: "forged" },
  ]) assert.equal(parse("market.filters.apply", forged), null);
  assert.equal(readAssistantBrowserAction({ type: "market.filters.apply", payload: base }, "/"), null);
  for (const range of ["5d", "1mo", "3mo", "6mo", "1y"]) {
    assert.deepEqual(parse("market.chart_range.set", { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", range }), {
      type: "market.chart_range.set", payload: { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", range },
    });
  }
  assert.equal(parse("market.chart_range.set", { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", range: "2y" }), null);
  assert.equal(parse("market.chart_range.set", { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", range: "1y", context_version: "forged" }), null);
  assert.deepEqual(parse("market.columns.set", { show_all_columns: true }), { type: "market.columns.set", payload: { show_all_columns: true } });
  assert.deepEqual(parse("market.columns.set", { show_all_columns: false }), { type: "market.columns.set", payload: { show_all_columns: false } });
  assert.equal(parse("market.columns.set", { show_all_columns: "true" }), null);
  for (const kind of ["quotes", "watchlist", "chart"]) assert.ok(parse("market.refresh", { kind }));
  assert.equal(parse("market.refresh", { kind: "all", force: true }), null);
});

test("webfetch preview retains the exact URL and rejects malformed confirmation data", () => {
  const url = "https://example.com/report?account_id=private%2fvalue&view=%2FResearch";
  const preview = {
    preview_id: "0123456789abcdef0123456789abcdef",
    url,
    reason: "Open the public report.",
    context_version: "a".repeat(64),
    expires_at: "2026-10-04T18:00:00+00:00",
    confirmation_phrase: "FETCH 89abcdef",
  };
  assert.deepEqual(readPrivateWebFetchPreview(preview), {
    preview_id: preview.preview_id,
    url,
    reason: preview.reason,
    context_version: preview.context_version,
    expires_at: preview.expires_at,
    confirmation_phrase: preview.confirmation_phrase,
  });
  assert.equal(readPrivateWebFetchPreview({ ...preview, url: "https://user:password@example.com/path" }), null);
  assert.equal(readPrivateWebFetchPreview({ ...preview, url: `${url}#fragment` }), null);
  assert.equal(readPrivateWebFetchPreview({ ...preview, confirmation_phrase: null }), null);
  assert.equal(readPrivateWebFetchPreview({ ...preview, extra: "unreviewed" }), null);
  assert.equal(readPrivateWebFetchPreview({ ...preview, preview_id: "123e4567-e89b-42d3-a456-426614174000" }), null);
  assert.equal(readPrivateWebFetchPreview({ ...preview, context_version: "ctx:version-1" }), null);
  assert.equal(readPrivateWebFetchPreview({ ...preview, url: `https://example.com/${"x".repeat(2048)}` }), null);
});

test("structured assistant answers preserve semantic rows and render hostile markup as inert text", () => {
  const blocks = parseAssistantAnswer([
    "## Forecast summary",
    "**Direction probabilities** are estimates from saved evidence.",
    "- Down: 20%",
    "- Unchanged: 15%",
    "- Up: 65%",
    "Horizon: Close to next close",
    "As of: 2025-01-10",
    "| Outcome | Probability |",
    "| --- | ---: |",
    "| Down | 20% |",
    "| Up | 65% |",
    "<img src=x onerror=alert(1)> https://example.invalid/private",
  ].join("\n"));
  assert.deepEqual(blocks.map((block) => block.kind), ["heading", "paragraph", "list", "key-values", "table", "paragraph"]);
  const literal = blocks.at(-1);
  assert.equal(literal.content[0].text, "<img src=x onerror=alert(1)> https://example.invalid/private");
  assert.equal(blocks.find((block) => block.kind === "table").rows.length, 2);
  assert.equal(blocks.some((block) => block.kind === "link"), false);
  assert.ok(blocks.every((block) => !Object.hasOwn(block, "html")));
  const overflow = parseAssistantAnswer("x".repeat(65_540));
  assert.equal(overflow.at(-1).kind, "overflow");
  assert.equal(overflow.at(-1).remaining.length, 4);
  const manySections = parseAssistantAnswer(Array.from({ length: 90 }, (_, index) => `## Section ${index}`).join("\n"));
  assert.equal(manySections.length, 80);
  assert.equal(manySections.at(-1).kind, "overflow");
  assert.equal(manySections.filter((block) => block.kind === "overflow").length, 1);
  assert.match(manySections.at(-1).remaining, /Section 79/);
});

test("turn submission preserves only server-resolved context, never its UI preview", () => {
  const context = {
    route: "/tools/forecast",
    instrument: { symbol: "SPY", asset_type: "etf", provider: "yahoo", exchange: "ARCA", display_name: "SPDR S&P 500 ETF Trust" },
    event_ref: { id: 14, version: "a".repeat(64) },
    result_ref: { id: 15, version: "b".repeat(64) },
    context_version: "c".repeat(64),
    preview: { summary: "Visible preview", fields: ["current route", "selected instrument"] },
  };
  assert.deepEqual(assistantTurnContext(context), {
    route: "/tools/forecast",
    instrument: { symbol: "SPY", asset_type: "etf", provider: "yahoo", exchange: "ARCA", display_name: "SPDR S&P 500 ETF Trust" },
    event_ref: { id: 14, version: "a".repeat(64) },
    result_ref: { id: 15, version: "b".repeat(64) },
    context_version: "c".repeat(64),
  });
});

test("SSE parser accepts only typed, monotonic records and allows error followed by final status", async () => {
  assert.deepEqual(parseAssistantSseFrame('id: 4\nevent: token\ndata: {"text":"hello"}'), {
    id: 4,
    name: "token",
    data: { text: "hello" },
  });
  assert.equal(parseAssistantSseFrame("event: unknown\ndata: {}"), null);
  assert.throws(() => parseAssistantSseFrame("id: zero\nevent: token\ndata: {}"), /invalid event cursor/);

  const stream = [
    'id: 1\nevent: error\ndata: {"code":"provider_unavailable","message":"Unavailable"}\n\n',
    'id: 2\nevent: complete\ndata: {"status":"failed","assistant_message_id":null}\n\n',
  ].join("");
  const events = [];
  const cursor = await consumeAssistantStream(new Response(stream, { headers: { "Content-Type": "text/event-stream" } }), 0, (entry) => events.push(entry));
  assert.equal(cursor, 2);
  assert.deepEqual(events.map((entry) => entry.event.type), ["error", "complete"]);

  const terminalStream = 'id: 1\nevent: complete\ndata: {"status":"completed"}\n\nid: 2\nevent: token\ndata: {"text":"late"}\n\n';
  await assert.rejects(
    consumeAssistantStream(new Response(terminalStream), 0, () => {}),
    /after a terminal event/,
  );
  await assert.rejects(
    consumeAssistantStream(new Response('id: 1\nevent: complete\ndata: {"status":"completed"}\n\nid: 1\nevent: complete\ndata: {"status":"completed"}\n\n'), 0, () => {}),
    /after a terminal event/,
  );
  await assert.rejects(
    consumeAssistantStream(new Response('id: 1\nevent: complete\ndata: {"status":"maybe"}\n\n'), 0, () => {}),
    /invalid terminal status/,
  );
});

test("assistant API wrappers reject paths outside the fixed local namespace", async () => {
  assert.throws(() => assistantApiPath("/api/v1/assistant/../auth/session"), /local assistant API/);
  assert.throws(() => assistantApiPath("https://example.test/api/v1/assistant/status"), /fixed local API route/);
});

test("terms links require HTTPS without embedded user credentials and stable HTTP errors stay helpful", () => {
  assert.equal(safeTermsUrl("https://provider.example.org/terms"), "https://provider.example.org/terms");
  assert.equal(safeTermsUrl("http://provider.example/terms"), undefined);
  assert.equal(safeTermsUrl("https://user:password@provider.example/terms"), undefined);
  for (const url of [
    "https://localhost/terms", "https://admin.local/terms", "https://127.0.0.1/terms",
    "https://10.0.0.1/terms", "https://[::1]/terms", "https://provider.example.test/terms",
    "https://provider.example.org:8443/terms", "https://provider.example.org/terms\n",
  ]) assert.equal(safeTermsUrl(url), undefined, url);
  assert.equal(safeAssistantCitationUrl("/?event_id=17#result-section"), "/?event_id=17#result-section");
  assert.equal(safeAssistantCitationUrl("/admin#invitations"), undefined);
  assert.equal(safeAssistantCitationUrl("/api/v1/history"), undefined);
  assert.equal(safeAssistantCitationUrl("/?event_id=17&event_id=18#result-section"), undefined);
  assert.equal(safeAssistantCitationUrl("https://public-source.example.org/article"), "https://public-source.example.org/article");
  assert.equal(safeAssistantCitationUrl("https://192.168.1.20/article"), undefined);
  assert.equal(safeAssistantCitationUrl("https://public-source.example.org:9443/article"), undefined);
  assert.match(assistantErrorMessage(428, "consent_required"), /privacy terms/);
  assert.match(assistantErrorMessage(409, "policy_version"), /policy changed.*current privacy terms/);
  assert.match(assistantErrorMessage(503, "worker_unavailable"), /workspace remains available/);
  assert.match(assistantErrorMessage(503, "assistant_cache_clear_pending"), /still saved\. Retry deletion shortly/);
});
