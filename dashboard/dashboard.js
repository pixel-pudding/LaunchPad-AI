/* ── LaunchPad-AI — Dashboard logic ──────────────────────────────────── */
/* Fetches real data from /api/decisions, /api/agent-status,             */
/* /api/portfolio-config, /api/repos. Markup/rendering only — every      */
/* endpoint, payload shape, and polling interval below is unchanged.     */

let allDecisions = [];
let currentPostPackage = null;
let autoMergeEnabled = true;
let activeStreamInterval = null;
let isAgentCurrentlyRunning = false;
let lastSeenDecisionId = null;
let expandedDeliveryIds = new Set();
let feedInitialized = false;
let isEditingPost = false;

// ── Tab Switching Navigation ──────────────────────────────────────────
function switchTab(tabName) {
    const landingView = document.getElementById("view-landing");
    const dashboardView = document.getElementById("view-dashboard");
    const landingTabBtn = document.getElementById("tab-btn-landing");
    const dashboardTabBtn = document.getElementById("tab-btn-dashboard");

    if (!landingView || !dashboardView) return;

    if (tabName === "dashboard") {
        landingView.style.display = "none";
        dashboardView.style.display = "block";
        if (landingTabBtn) landingTabBtn.classList.remove("active");
        if (dashboardTabBtn) dashboardTabBtn.classList.add("active");
        if (window.location.hash !== "#dashboard") {
            window.location.hash = "dashboard";
        }
    } else {
        landingView.style.display = "block";
        dashboardView.style.display = "none";
        if (landingTabBtn) landingTabBtn.classList.add("active");
        if (dashboardTabBtn) dashboardTabBtn.classList.remove("active");
        if (window.location.hash !== "#overview") {
            window.location.hash = "overview";
        }
    }
}

function applyHashRoute() {
    const hash = window.location.hash.replace("#", "");
    if (hash === "dashboard") {
        switchTab("dashboard");
    } else {
        switchTab("landing");
    }
}

window.addEventListener("hashchange", applyHashRoute);
window.switchTab = switchTab;
window.connectPortfolioRepo = connectPortfolioRepo;
window.editPortfolioRepo = editPortfolioRepo;
window.toggleTerminalExpansion = toggleTerminalExpansion;
window.onAutoMergeToggleChanged = onAutoMergeToggleChanged;
window.copyPostContent = copyPostContent;
window.copyPostImage = copyPostImage;
window.editPostContent = editPostContent;
window.renderNutshellDemo = renderNutshellDemo;
window.toggleRowExpand = toggleRowExpand;
window.toggleActivityFeed = toggleActivityFeed;

// ── Portfolio Configuration State & Persistence ──────────────────────
async function loadAutoMergeConfig() {
    try {
        const resp = await fetch("/api/portfolio-config");
        if (resp.ok) {
            const data = await resp.json();
            if (data && typeof data.auto_merge === "boolean") {
                updateAutoMergeUI(data.auto_merge);
            }
        }
    } catch (e) {
        console.warn("Could not fetch portfolio config for auto-merge toggle:", e);
    }
}

function updateAutoMergeUI(enabled) {
    autoMergeEnabled = !!enabled;
    const onboardingToggle = document.getElementById("onboarding-automerge-toggle");
    const onboardingLabel = document.getElementById("onboarding-automerge-label");
    const dashStatusText = document.getElementById("dash-automerge-status-text");

    if (onboardingToggle) onboardingToggle.checked = autoMergeEnabled;
    if (onboardingLabel) onboardingLabel.textContent = autoMergeEnabled ? "AUTO-MERGE: ON" : "AUTO-MERGE: OFF";
    if (dashStatusText) dashStatusText.textContent = autoMergeEnabled ? "Auto-merge active" : "Manual review mode";
}

async function onAutoMergeToggleChanged(checked) {
    updateAutoMergeUI(checked);
    const saveState = document.getElementById("automerge-save-state");
    const savedRepo = localStorage.getItem("launchpad_portfolio_repo") || "";
    if (saveState) saveState.textContent = "saving…";
    try {
        await fetch("/api/portfolio-config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                portfolio_repo: savedRepo,
                format: "arbitrary",
                auto_merge: checked
            })
        });
        if (saveState) {
            saveState.textContent = "saved";
            setTimeout(() => { if (saveState) saveState.textContent = ""; }, 2000);
        }
        showToast(checked ? "Auto-merge enabled — verified releases will merge automatically." : "Manual review mode enabled for future releases.");
    } catch (e) {
        console.warn("Failed to persist auto-merge state to server:", e);
        if (saveState) saveState.textContent = "failed to save";
    }
}

// ── Connected Portfolio Target Repo Logic ─────────────────────────────
function parseRepoSlug(input) {
    if (!input) return "";
    let clean = input.trim();
    clean = clean.replace(/^https?:\/\/(www\.)?github\.com\//i, "");
    clean = clean.replace(/\.git$/i, "");
    clean = clean.replace(/\/+$/, "");
    return clean;
}

async function loadConnectedPortfolioRepo() {
    let saved = localStorage.getItem("launchpad_portfolio_repo") || "";
    try {
        const resp = await fetch("/api/portfolio-config");
        if (resp.ok) {
            const data = await resp.json();
            if (data && data.portfolio_repo) {
                saved = data.portfolio_repo;
                localStorage.setItem("launchpad_portfolio_repo", saved);
            }
            if (data && typeof data.auto_merge === "boolean") {
                updateAutoMergeUI(data.auto_merge);
            }
        }
    } catch (e) {
        console.warn("Could not fetch portfolio config from server:", e);
    }

    const inputWrapper = document.getElementById("repo-input-wrapper");
    const connectedState = document.getElementById("repo-connected-state");
    const nameDisplay = document.getElementById("portfolio-target-name");
    const inputEl = document.getElementById("portfolio-repo-input");

    if (saved && nameDisplay && inputWrapper && connectedState) {
        nameDisplay.textContent = saved;
        inputWrapper.style.display = "none";
        connectedState.style.display = "flex";
        if (inputEl) inputEl.value = saved;
    } else if (inputWrapper && connectedState) {
        inputWrapper.style.display = "flex";
        connectedState.style.display = "none";
        if (inputEl) inputEl.value = "";
    }
}

async function connectPortfolioRepo() {
    const inputEl = document.getElementById("portfolio-repo-input");
    if (!inputEl) return;
    const slug = parseRepoSlug(inputEl.value);

    if (!slug || !slug.includes("/")) {
        showToast("Please enter a valid repo (e.g. username/portfolio or GitHub URL).");
        return;
    }

    try {
        await fetch("/api/portfolio-config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                portfolio_repo: slug,
                format: "arbitrary",
                auto_merge: autoMergeEnabled
            }),
        });
    } catch (e) {
        console.warn("Could not save portfolio config to server:", e);
    }

    localStorage.setItem("launchpad_portfolio_repo", slug);
    loadConnectedPortfolioRepo();
    showToast(`Connected ${slug} as your portfolio repo.`);
}

function editPortfolioRepo() {
    const inputWrapper = document.getElementById("repo-input-wrapper");
    const connectedState = document.getElementById("repo-connected-state");
    const inputEl = document.getElementById("portfolio-repo-input");

    if (inputWrapper && connectedState) {
        inputWrapper.style.display = "flex";
        connectedState.style.display = "none";
        if (inputEl) {
            inputEl.value = "";
            inputEl.focus();
        }
    }
}

// ── "Agent in a nutshell" static sample-release demo (Overview) ──────
// Illustrative teaching content only -- not live data, no fetch involved.
const NUTSHELL_DEMOS = [
    {
        label: "your-project v1.0.0",
        action: "feature_new",
        reason: "A brand-new capability with no existing entry — a new project card is written.",
        tiles: [
            { title: "Portfolio updated", detail: "new card added, merged and live on your site" },
            { title: "LinkedIn post ready", detail: "draft ready — copy and publish" }
        ],
        byproduct: "Byproduct: suggested next build — an evaluation harness."
    },
    {
        label: "your-project v1.1.0",
        action: "update_existing",
        reason: "Already featured — this release adds something real, so the existing entry is updated.",
        tiles: [
            { title: "Portfolio updated", detail: "new card added, merged and live on your site" },
            { title: "LinkedIn post ready", detail: "draft ready — copy and publish" }
        ],
        byproduct: "Byproduct: suggested next build — an evaluation harness."
    },
    {
        label: "your-config v2.0.1",
        action: "skip",
        reason: "Config bump only — not portfolio-notable, so the agent leaves everything untouched.",
        tiles: [
            { title: "Nothing published", detail: "the agent assessed it and chose not to touch your portfolio" }
        ],
        byproduct: null
    }
];

function actionLabel(action) {
    return (action || "skip").toUpperCase().replace(/_/g, " ");
}

function renderNutshellDemo(idx) {
    const demo = NUTSHELL_DEMOS[idx];
    if (!demo) return;

    const chipsEl = document.getElementById("nutshell-chips");
    if (chipsEl) {
        chipsEl.innerHTML = NUTSHELL_DEMOS.map((d, i) =>
            `<button type="button" class="nutshell-chip font-mono-lp${i === idx ? " active" : ""}" onclick="renderNutshellDemo(${i})">${escapeHtml(d.label)}</button>`
        ).join("");
    }

    const badge = document.getElementById("nutshell-badge");
    if (badge) {
        badge.textContent = actionLabel(demo.action);
        badge.className = `decision-badge font-mono-lp badge-${demo.action}`;
    }

    setText("nutshell-reason", demo.reason);

    const tilesEl = document.getElementById("nutshell-tiles");
    if (tilesEl) {
        tilesEl.className = `nutshell-tiles${demo.tiles.length === 1 ? " single" : ""}`;
        tilesEl.innerHTML = demo.tiles.map(t => `
            <div class="nutshell-tile">
                <div class="nutshell-tile-title">${escapeHtml(t.title)}</div>
                <div class="nutshell-tile-detail">${escapeHtml(t.detail)}</div>
            </div>
        `).join("");
    }

    const byproductEl = document.getElementById("nutshell-byproduct");
    if (byproductEl) {
        if (demo.byproduct) {
            byproductEl.style.display = "block";
            byproductEl.textContent = demo.byproduct;
        } else {
            byproductEl.style.display = "none";
        }
    }
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

// ── Live Agent Status Banner ───────────────────────────────────────────
let currentAgentExecutionState = "idle"; // "idle" | "running"
let isTerminalExpanded = false;
let lastRunDuration = "";
let currentRunningRepo = "";

const MIN_STAGE_GLOW_MS = 3000;
let highestStageByDelivery = new Map();
let visualStageByDelivery = new Map();
let stageActivatedAtByDelivery = new Map();
let lastSeenRunningDeliveryId = null;

function renderTerminalHeader() {
    const titleEl = document.getElementById("terminal-status-title");
    const descEl = document.getElementById("terminal-status-desc");
    const dotEl = document.getElementById("terminal-status-dot");
    const toggleBtn = document.getElementById("btn-terminal-toggle");
    const timerBadge = document.getElementById("terminal-timer-badge");
    const stagesContainer = document.getElementById("terminal-stages-collapsible");
    const container = document.getElementById("live-terminal-container");

    if (currentAgentExecutionState === "running") {
        if (titleEl) titleEl.textContent = "AGENT RUNNING";
        if (descEl) descEl.textContent = currentRunningRepo ? `· Processing ${currentRunningRepo}` : "· Processing a release";
        if (dotEl) dotEl.className = "dot-indicator pulse";
        if (timerBadge) timerBadge.style.display = "inline-block";
        if (container) container.classList.add("running");
    } else {
        if (container) container.classList.remove("running");
        if (titleEl) titleEl.textContent = "AGENT IDLE";
        if (descEl) descEl.textContent = lastRunDuration
            ? `· Last run completed in ${lastRunDuration}`
            : "· Watching connected repositories for tagged releases";
        if (dotEl) dotEl.className = "dot-indicator";
        if (timerBadge) timerBadge.style.display = "none";
    }

    if (toggleBtn) toggleBtn.textContent = isTerminalExpanded ? "Hide stages ▴" : "View stages ▾";
    if (stagesContainer) stagesContainer.style.display = isTerminalExpanded ? "block" : "none";
}

function toggleTerminalExpansion() {
    isTerminalExpanded = !isTerminalExpanded;
    renderTerminalHeader();
}

function renderStageVisuals(deliveryId, currentVisualStage) {
    const stageItems = [1, 2, 3, 4, 5, 6].map(n => document.getElementById(`stage-${n}`));
    stageItems.forEach((el, idx) => {
        if (!el) return;
        const stageNum = idx + 1;
        el.className = stageNum < currentVisualStage ? "terminal-stage-item done"
            : stageNum === currentVisualStage ? "terminal-stage-item active"
            : "terminal-stage-item pending";
    });
}

// ── Real-Time Agent Telemetry Polling (/api/agent-status) ────────────
async function pollAgentStatus() {
    try {
        const resp = await fetch("/api/agent-status");
        if (!resp.ok) return;
        const statusData = await resp.json();

        const timerBadge = document.getElementById("terminal-timer-badge");
        const stageItems = [1, 2, 3, 4, 5, 6].map(n => document.getElementById(`stage-${n}`));

        if (statusData && statusData.status === "running") {
            const deliveryId = statusData.delivery_id || "";
            const isNewRun = deliveryId !== lastSeenRunningDeliveryId;
            lastSeenRunningDeliveryId = deliveryId;
            currentRunningRepo = statusData.repo || "";

            const targetStage = statusData.stage || 1;
            const previousHighest = highestStageByDelivery.get(deliveryId) || 0;
            const currentStage = Math.max(targetStage, previousHighest);
            highestStageByDelivery.set(deliveryId, currentStage);

            const now = Date.now();
            let visualStage = visualStageByDelivery.get(deliveryId) || 0;
            let stageActivatedAt = stageActivatedAtByDelivery.get(deliveryId) || 0;

            if (visualStage === 0 || isNewRun) {
                visualStage = 1;
                visualStageByDelivery.set(deliveryId, 1);
                stageActivatedAtByDelivery.set(deliveryId, now);
            } else if (visualStage < currentStage && (now - stageActivatedAt >= MIN_STAGE_GLOW_MS)) {
                visualStage += 1;
                visualStageByDelivery.set(deliveryId, visualStage);
                stageActivatedAtByDelivery.set(deliveryId, now);
            }

            if (!isAgentCurrentlyRunning || isNewRun) {
                isAgentCurrentlyRunning = true;
                currentAgentExecutionState = "running";
                isTerminalExpanded = true;
                renderTerminalHeader();
            }

            const serverStart = statusData.started_at ? new Date(statusData.started_at).getTime() : Date.now();
            const elapsed = Math.max(0, ((Date.now() - serverStart) / 1000)).toFixed(1);
            if (timerBadge) {
                timerBadge.style.display = "inline-block";
                timerBadge.textContent = `${elapsed}s elapsed`;
            }

            renderStageVisuals(deliveryId, visualStage);
        } else if (isAgentCurrentlyRunning && (!statusData || statusData.status === "idle")) {
            // Check if visual stages still need to complete their 3s display
            const deliveryId = lastSeenRunningDeliveryId || "";
            const now = Date.now();
            let visualStage = visualStageByDelivery.get(deliveryId) || 6;
            let stageActivatedAt = stageActivatedAtByDelivery.get(deliveryId) || 0;

            if (visualStage < 6 && (now - stageActivatedAt >= MIN_STAGE_GLOW_MS)) {
                visualStage += 1;
                visualStageByDelivery.set(deliveryId, visualStage);
                stageActivatedAtByDelivery.set(deliveryId, now);
                renderStageVisuals(deliveryId, visualStage);
                return;
            } else if (visualStage < 6) {
                renderStageVisuals(deliveryId, visualStage);
                return;
            }

            // Finished execution.
            isAgentCurrentlyRunning = false;
            currentAgentExecutionState = "idle";
            highestStageByDelivery.clear();
            visualStageByDelivery.clear();
            stageActivatedAtByDelivery.clear();
            lastSeenRunningDeliveryId = null;

            stageItems.forEach(el => { if (el) el.className = "terminal-stage-item done"; });

            lastRunDuration = statusData.duration_seconds
                ? `${statusData.duration_seconds}s`
                : (statusData.started_at && statusData.completed_at
                    ? `${((new Date(statusData.completed_at) - new Date(statusData.started_at)) / 1000).toFixed(1)}s`
                    : "");
            renderTerminalHeader();

            // Reload decisions immediately so the new card & post appear without a refresh.
            await loadDecisions();

            setTimeout(() => {
                if (!isAgentCurrentlyRunning) {
                    isTerminalExpanded = false;
                    renderTerminalHeader();
                }
            }, 20000);
        }
    } catch (e) {
        console.warn("Could not poll agent status:", e);
    }
}

// ── Agent Voice Narration Helpers ──────────────────────────────────────
function summarizeDecision(decision) {
    const action = decision.action || "skip";
    if (action === "feature_new") return "New capability — added to your portfolio.";
    if (action === "update_existing") return "Existing card refreshed.";
    return "Assessed — not portfolio-notable.";
}

function formatAgentVoice(decision) {
    const action = decision.action || "skip";
    const rawReason = decision.reasoning || "";
    const repo = decision.repo || "this project";

    if (rawReason.toLowerCase().startsWith("i evaluated") || rawReason.toLowerCase().startsWith("i looked") || rawReason.toLowerCase().startsWith("i analyzed")) {
        return rawReason;
    }

    if (action === "skip") {
        return `I evaluated the changelog and release diff for ${repo} — dependency updates and minor maintenance only. Nothing here alters your core technical capability, so I left your portfolio untouched.`;
    } else if (action === "feature_new") {
        return `I analyzed the codebase and release notes for ${repo}: new capabilities detected. I wrote a new project card and staged your launch announcement.`;
    } else {
        return `I matched ${repo} against your existing portfolio entry. Refreshed the summary and bumped the version line.`;
    }
}

// ── Decision Feed Fetching ──────────────────────────────────────────────
function decisionKey(d) {
    return d.delivery_id || d.id || (d.repo + "_" + (d.tag || "") + "_" + (d.ts || ""));
}

function formatTagLabel(tag) {
    return tag ? `v${tag.replace(/^v/, "")}` : "";
}

async function loadDecisions() {
    try {
        const resp = await fetch("/api/decisions");
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const decisions = await resp.json();

        allDecisions = decisions || [];
        const latest = allDecisions[0];
        const latestId = latest ? decisionKey(latest) : null;
        const isNewRelease = !!(latest && lastSeenDecisionId && lastSeenDecisionId !== latestId);

        renderDashboard(allDecisions, isNewRelease);
        lastSeenDecisionId = latestId;
    } catch (err) {
        console.error("Failed to fetch decisions:", err);
    }
}

// ── Dashboard rendering: "Latest release" twin cards + activity feed ──
function renderDashboard(decisions, animateLatest) {
    const hasAny = decisions && decisions.length > 0;
    const emptyState = document.getElementById("dash-empty-state");
    const twinCards = document.getElementById("dash-twin-cards");
    const activityGrid = document.getElementById("dash-activity-grid");
    const countPill = document.getElementById("nav-decisions-count");
    const titleEl = document.getElementById("dash-latest-title");
    const handledPill = document.getElementById("dash-handled-pill");

    if (countPill) countPill.textContent = hasAny ? decisions.length.toString() : "0";

    if (!hasAny) {
        if (emptyState) emptyState.style.display = "block";
        if (twinCards) twinCards.style.display = "none";
        if (activityGrid) activityGrid.style.display = "none";
        if (titleEl) titleEl.textContent = "No releases yet";
        if (handledPill) handledPill.style.display = "none";
        return;
    }

    if (emptyState) emptyState.style.display = "none";
    if (twinCards) twinCards.style.display = "grid";
    if (activityGrid) activityGrid.style.display = "block";

    const latest = decisions[0];
    if (titleEl) {
        const tag = latest.tag ? ` ${formatTagLabel(latest.tag)}` : "";
        titleEl.textContent = `Latest release · ${latest.repo || "unknown repo"}${tag}`;
    }
    if (handledPill) {
        if (latest.ts) {
            handledPill.style.display = "inline-block";
            handledPill.textContent = `handled ${formatRelativeTime(latest.ts)}`;
        } else {
            handledPill.style.display = "none";
        }
    }

    if (!isEditingPost) {
        renderTwinCards(latest, animateLatest);
    }
    renderActivityFeed(decisions);
    renderByproductFootnote(latest);
}

function renderTwinCards(decision, shouldAnimateTypewriter) {
    currentPostPackage = decision;
    const artifacts = decision.artifacts || {};
    const action = decision.action || "skip";
    const isAutoMerged = !!artifacts.portfolio_pr_merged;
    const hasPr = !!artifacts.portfolio_pr;

    const pStatusPill = document.getElementById("portfolio-status-pill");
    const pStatusText = document.getElementById("portfolio-status-text");
    const pTitle = document.getElementById("portfolio-title");
    const pEmpty = document.getElementById("portfolio-empty");
    const pActions = document.getElementById("portfolio-actions");
    const pDiffBox = document.getElementById("portfolio-diff-box");

    if (pActions) pActions.innerHTML = "";

    if (hasPr) {
        if (pStatusPill) pStatusPill.classList.remove("muted");
        if (pStatusText) pStatusText.textContent = isAutoMerged ? "PORTFOLIO UPDATED" : "REVIEW PR OPEN";
        if (pTitle) pTitle.textContent = isAutoMerged ? "Merged into your site" : "Waiting on your review";
        if (pEmpty) pEmpty.style.display = "none";
        if (pDiffBox) {
            pDiffBox.style.display = "block";
            pDiffBox.textContent = `${decision.repo || ""} — ${summarizeDecision(decision)}`;
        }
        if (pActions) {
            const chip = document.createElement("a");
            chip.className = `btn-portfolio-pr font-mono-lp${isAutoMerged ? "" : " review"}`;
            chip.href = artifacts.portfolio_pr;
            chip.target = "_blank";
            chip.rel = "noopener";
            chip.textContent = isAutoMerged ? "View merged PR" : "Review PR on GitHub";
            pActions.appendChild(chip);
        }
    } else {
        if (pStatusPill) pStatusPill.classList.add("muted");
        if (pStatusText) pStatusText.textContent = action === "skip" ? "NOT APPLICABLE" : "NO PORTFOLIO CONNECTED";
        if (pTitle) pTitle.textContent = action === "skip" ? "Nothing to update" : "No portfolio repo connected";
        if (pDiffBox) pDiffBox.style.display = "none";
        if (pEmpty) {
            pEmpty.style.display = "block";
            pEmpty.textContent = action === "skip"
                ? "This release was assessed as not portfolio-notable — nothing changed."
                : "Connect a portfolio repo on the Overview tab to let the agent update it automatically.";
        }
    }

    renderPublishCard(decision, !!shouldAnimateTypewriter);
}

function renderPublishCard(decision, shouldAnimateTypewriter) {
    const artifacts = decision.artifacts || {};
    const pkg = artifacts.post_package || {};
    const action = decision.action || "skip";
    const body = document.getElementById("publish-body");
    const statusPill = document.getElementById("publish-status-pill");
    const statusText = document.getElementById("publish-status-text");
    const titleEl = document.getElementById("publish-title");

    if (!body) return;

    if (action === "skip" || !pkg.text) {
        if (statusPill) statusPill.classList.add("muted");
        if (statusText) statusText.textContent = "NO POST DRAFTED";
        if (titleEl) titleEl.textContent = "Nothing to publish this time";
        body.innerHTML = `
            <div class="restraint-box">
                <strong>Editorial restraint</strong>
                This release was assessed as maintenance or a minor patch — not worth a LinkedIn post. Your feed
                stays high-signal, and nothing was changed on your live site.
            </div>
        `;
        return;
    }

    if (statusPill) statusPill.classList.remove("muted");
    if (statusText) statusText.textContent = "PUBLISH READY";
    const key = decisionKey(decision);
    const savedEdit = localStorage.getItem(`launchpad_post_edit_${key}`);
    const isCustomEdited = !!savedEdit && savedEdit !== pkg.text;
    const fullText = savedEdit || pkg.text || "";

    const hashtags = (pkg.hashtags || [])
        .map(t => `<span class="post-hashtag-chip font-mono-lp">${escapeHtml(t.startsWith("#") ? t : "#" + t)}</span>`)
        .join("");

    body.innerHTML = `
        <div class="post-top-action-bar">
            <div class="post-actions-row-top">
                <button class="btn-copy-post font-mono-lp" id="btn-copy" onclick="copyPostContent()">Copy post &amp; open LinkedIn</button>
                <button class="btn-copy-image font-mono-lp" id="btn-copy-img" onclick="copyPostImage()">Copy image</button>
                <button class="btn-edit-post font-mono-lp" id="btn-edit-post" onclick="editPostContent()">${isEditingPost ? "Save" : "Edit"}</button>
                ${isCustomEdited ? `<button class="btn-reset-post font-mono-lp" id="btn-reset-post" onclick="resetPostContent('${key}')" title="Revert to Gemini's generated draft">Reset to generated</button>` : ""}
            </div>
            <div class="post-reasoning-quote font-mono-lp">"${escapeHtml(summarizeDecision(decision))}"</div>
        </div>
        <div class="post-body-grid">
            <div class="post-text-content" id="post-text"></div>
            <div class="post-image-box" id="post-image-container"${pkg.image_url ? "" : ' style="display:none;"'}>
                ${pkg.image_url ? `<img id="post-image" src="${escapeHtml(pkg.image_url)}" alt="Generated post image" />` : ""}
            </div>
        </div>
        <div class="post-hashtags-wrap" id="post-hashtags">${hashtags}</div>
        <span class="copy-post-hint font-mono-lp" style="margin-top:4px;">${isCustomEdited ? "Custom draft saved locally · Copies text + hashtags, then opens LinkedIn." : "Copies text + hashtags, then opens LinkedIn."}</span>
    `;

    const textEl = document.getElementById("post-text");
    if (activeStreamInterval) clearInterval(activeStreamInterval);

    if (shouldAnimateTypewriter && textEl && !isCustomEdited) {
        const words = fullText.split(" ");
        let wordIdx = 0;
        textEl.innerHTML = `<span class="typewriter-cursor">▌</span>`;
        activeStreamInterval = setInterval(() => {
            if (wordIdx < words.length) {
                const currentText = words.slice(0, wordIdx + 1).join(" ");
                textEl.innerHTML = escapeHtml(currentText) + `<span class="typewriter-cursor">▌</span>`;
                wordIdx++;
            } else {
                clearInterval(activeStreamInterval);
                textEl.textContent = fullText;
            }
        }, 35);
    } else if (textEl) {
        textEl.textContent = fullText;
    }
}

function renderByproductFootnote(decision) {
    const footnoteEl = document.getElementById("quiet-next-build-footnote");
    const wrapperEl = document.getElementById("next-build-card-wrapper");
    if (!footnoteEl) return;

    const artifacts = decision.artifacts || {};
    const nextBuilds = artifacts.next_builds || decision.next_builds || [];
    if (nextBuilds && nextBuilds.length > 0) {
        const first = nextBuilds[0];
        const title = first.title || first.text || first.name || "";
        const reason = first.one_line_reason || first.reason || "";
        if (title || reason) {
            if (wrapperEl) wrapperEl.style.display = "block";
            footnoteEl.style.display = "block";
            footnoteEl.innerHTML = `
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <span class="footnote-label font-mono-lp" style="color:var(--sage-text); font-weight:700; font-size:10.5px; letter-spacing:0.08em;">💡 WHAT TO BUILD NEXT</span>
                    <strong style="font-size:14px; color:var(--text-primary);">${escapeHtml(title)}</strong>
                    ${reason ? `<span style="font-size:12.5px; color:var(--text-secondary); line-height:1.5;">${escapeHtml(reason)}</span>` : ""}
                </div>
            `;
            return;
        }
    }
    if (wrapperEl) wrapperEl.style.display = "none";
    footnoteEl.style.display = "none";
}

// ── Agent activity feed: collapse the whole feed to focus elsewhere ───
let isFeedCollapsed = false;

function toggleActivityFeed() {
    isFeedCollapsed = !isFeedCollapsed;
    const list = document.getElementById("decision-log");
    const btn = document.getElementById("btn-feed-collapse");
    if (list) list.style.display = isFeedCollapsed ? "none" : "flex";
    if (btn) btn.textContent = isFeedCollapsed ? "Expand ▾" : "Collapse ▴";
}

// ── Agent activity feed: collapsed one-liners, expand for reasoning ───
function toggleRowExpand(key) {
    if (expandedDeliveryIds.has(key)) expandedDeliveryIds.delete(key);
    else expandedDeliveryIds.add(key);
    renderActivityFeed(allDecisions);
}

function renderActivityFeed(decisions) {
    const container = document.getElementById("decision-log");
    if (!container) return;

    if (!feedInitialized && decisions.length > 0) {
        expandedDeliveryIds.add(decisionKey(decisions[0]));
        feedInitialized = true;
    }

    container.innerHTML = "";

    decisions.forEach(d => {
        const key = decisionKey(d);
        const action = d.action || "skip";
        const isExpanded = expandedDeliveryIds.has(key);
        const tsFull = d.ts ? formatTimestamp(d.ts) : "";
        const tsRelative = d.ts ? formatRelativeTime(d.ts) : "";
        const repo = d.repo || "unknown/repo";
        const tag = d.tag ? formatTagLabel(d.tag) : "";
        const summary = summarizeDecision(d);
        const artifacts = d.artifacts || {};

        const item = document.createElement("div");
        item.className = `decision-row-item action-${action}`;

        const btn = document.createElement("button");
        btn.className = "decision-row-btn";
        btn.setAttribute("aria-expanded", isExpanded ? "true" : "false");
        btn.onclick = () => toggleRowExpand(key);
        btn.innerHTML = `
            <span class="decision-row-time font-mono-lp" title="${escapeHtml(tsFull)}">${escapeHtml(tsRelative)}</span>
            <span class="decision-badge font-mono-lp badge-${action}">${escapeHtml(actionLabel(action))}</span>
            <span class="decision-repo-name font-mono-lp">${escapeHtml(repo)}</span>
            ${tag ? `<span class="font-mono-lp" style="font-size:11px;color:var(--text-dim);">${escapeHtml(tag)}</span>` : ""}
            <span class="decision-summary-text">${escapeHtml(summary)}</span>
            <span class="decision-expand-toggle font-mono-lp">${isExpanded ? "−" : "+"} why</span>
        `;
        item.appendChild(btn);

        if (isExpanded) {
            const panel = document.createElement("div");
            panel.className = "decision-expand-panel";
            let linksHtml = "";
            if (artifacts.portfolio_pr) {
                const merged = !!artifacts.portfolio_pr_merged;
                linksHtml += `<a class="pr-link-chip font-mono-lp${merged ? " merged" : ""}" href="${escapeHtml(artifacts.portfolio_pr)}" target="_blank" rel="noopener" onclick="event.stopPropagation();">Portfolio PR ${merged ? "— merged" : "— open for review"}</a>`;
            }
            if (artifacts.readme_pr) {
                linksHtml += `<a class="pr-link-chip font-mono-lp" href="${escapeHtml(artifacts.readme_pr)}" target="_blank" rel="noopener" onclick="event.stopPropagation();">README PR</a>`;
            }
            panel.innerHTML = `
                <p class="agent-narrative-box">"${escapeHtml(formatAgentVoice(d))}"</p>
                ${linksHtml ? `<div class="decision-links-row">${linksHtml}</div>` : ""}
            `;
            item.appendChild(panel);
        }

        container.appendChild(item);
    });
}

// ── Copy Post & Open LinkedIn ─────────────────────────────────────────
function copyPostContent() {
    if (!currentPostPackage) {
        showToast("No active post draft to copy.");
        return;
    }

    const key = decisionKey(currentPostPackage);
    const savedEdit = localStorage.getItem(`launchpad_post_edit_${key}`);
    const artifacts = currentPostPackage.artifacts || {};
    const pkg = artifacts.post_package || {};
    const text = savedEdit || pkg.text || "";
    const hashtags = (pkg.hashtags || []).map(t => t.startsWith("#") ? t : `#${t}`).join(" ");
    const fullContent = hashtags ? `${text}\n\n${hashtags}` : text;

    navigator.clipboard.writeText(fullContent).then(() => {
        showToast("Copied — opening LinkedIn.");
        const btn = document.getElementById("btn-copy");
        if (btn) {
            btn.textContent = "✓ Copied";
            btn.classList.add("copied");
            setTimeout(() => {
                btn.innerHTML = "Copy post &amp; open LinkedIn";
                btn.classList.remove("copied");
            }, 2500);
        }
        window.open("https://www.linkedin.com/feed/?shareActive=true", "_blank");
    }).catch(err => {
        console.error("Clipboard copy failed:", err);
        showToast("Copy failed — please copy manually.");
        window.open("https://www.linkedin.com/feed/?shareActive=true", "_blank");
    });
}

// ── Copy Project Preview Image ─────────────────────────────────────────
async function copyPostImage() {
    if (!currentPostPackage) {
        showToast("No active image to copy.");
        return;
    }
    const artifacts = currentPostPackage.artifacts || {};
    const pkg = artifacts.post_package || {};
    const imageUrl = pkg.image_url;

    if (!imageUrl) {
        showToast("No image attached to this release.");
        return;
    }

    try {
        showToast("Fetching image for clipboard...");
        const response = await fetch(imageUrl);
        const blob = await response.blob();
        await navigator.clipboard.write([
            new ClipboardItem({ [blob.type]: blob })
        ]);
        showToast("Image copied — paste directly into LinkedIn.");
    } catch (err) {
        console.warn("Direct blob clipboard write failed, opening image URL:", err);
        window.open(imageUrl, "_blank");
        showToast("Opened full-resolution image in a new tab.");
    }
}

function editPostContent() {
    const textEl = document.getElementById("post-text");
    const btn = document.getElementById("btn-edit-post");
    if (!textEl) return;

    if (isEditingPost) {
        // Save
        isEditingPost = false;
        textEl.setAttribute("contenteditable", "false");
        textEl.classList.remove("editing-active");
        if (btn) {
            btn.textContent = "Edit";
            btn.classList.remove("btn-save-active");
        }
        const editedText = textEl.innerText.trim();
        if (currentPostPackage) {
            const key = decisionKey(currentPostPackage);
            localStorage.setItem(`launchpad_post_edit_${key}`, editedText);
            if (currentPostPackage.artifacts && currentPostPackage.artifacts.post_package) {
                currentPostPackage.artifacts.post_package.text = editedText;
            }
        }
        showToast("Draft saved locally.");
        renderPublishCard(currentPostPackage, false);
    } else {
        // Start editing
        isEditingPost = true;
        textEl.setAttribute("contenteditable", "true");
        textEl.classList.add("editing-active");
        textEl.focus();
        if (btn) {
            btn.textContent = "Save";
            btn.classList.add("btn-save-active");
        }
        showToast("Editing mode active. Click Save when finished.");
    }
}

function resetPostContent(key) {
    localStorage.removeItem(`launchpad_post_edit_${key}`);
    showToast("Reset to generated draft.");
    if (currentPostPackage) {
        renderPublishCard(currentPostPackage, false);
    }
}

// ── Helpers & Formatting ──────────────────────────────────────────────
function showToast(message) {
    let toast = document.getElementById("global-toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "global-toast";
        toast.className = "toast font-mono-lp";
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 3200);
}

function formatTimestamp(ts) {
    try {
        const d = new Date(ts);
        return d.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false
        }) + " UTC";
    } catch {
        return ts;
    }
}

function formatRelativeTime(ts) {
    try {
        const now = new Date();
        const past = new Date(ts);
        const diffMs = now - past;
        const diffMins = Math.floor(diffMs / (1000 * 60));
        if (diffMins < 1) return "just now";
        if (diffMins < 60) return `${diffMins}m ago`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours}h ago`;
        const diffDays = Math.floor(diffHours / 24);
        return `${diffDays}d ago`;
    } catch {
        return "recently";
    }
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ── Application Initialization ────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    applyHashRoute();
    loadConnectedPortfolioRepo();
    loadAutoMergeConfig();
    renderNutshellDemo(0);

    // Initial data fetch
    loadDecisions();
    pollAgentStatus();

    // Real-time telemetry polling (every 350ms so the live stage view feels instant)
    setInterval(() => {
        pollAgentStatus();
    }, 350);

    // Adaptive decisions polling (every 3s)
    setInterval(() => {
        if (!isAgentCurrentlyRunning) {
            loadDecisions();
        }
    }, 3000);
});
