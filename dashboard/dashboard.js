/* ── LaunchPad AI — Modern Cockpit Dashboard Logic ──────────────────── */
/* Features: Real-time Live Streaming, Agent Voice, Auto-Merge Sync,    */
/* 62/38 Cockpit Layout, Top-Pinned Action Buttons, Adaptive Polling.     */

let allDecisions = [];
let selectedDeliveryId = null;
let currentPostPackage = null;
let autoMergeEnabled = true;
let activeStreamInterval = null;
let isAgentCurrentlyRunning = false;
let agentRunStartTime = null;
let agentTimerInterval = null;
let lastSeenDecisionId = null;

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
window.toggleDecisionSidebar = toggleDecisionSidebar;
window.toggleTerminalExpansion = toggleTerminalExpansion;
window.onAutoMergeToggleChanged = onAutoMergeToggleChanged;
window.copyPostContent = copyPostContent;
window.copyPostImage = copyPostImage;
window.editPostContent = editPostContent;

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
    const headerToggle = document.getElementById("header-automerge-toggle");
    const headerLabel = document.getElementById("header-automerge-label");
    const onboardingToggle = document.getElementById("onboarding-automerge-toggle");
    const onboardingLabel = document.getElementById("onboarding-automerge-label");
    const dashStatusPill = document.getElementById("dash-automerge-status-pill");

    if (headerToggle) headerToggle.checked = autoMergeEnabled;
    if (onboardingToggle) onboardingToggle.checked = autoMergeEnabled;

    if (headerLabel) {
        headerLabel.textContent = autoMergeEnabled ? "AUTO-MERGE: ON" : "AUTO-MERGE: OFF";
        headerLabel.style.color = autoMergeEnabled ? "var(--accent-sage)" : "var(--text-muted)";
    }

    if (onboardingLabel) {
        onboardingLabel.textContent = autoMergeEnabled ? "AUTO-MERGE: ON" : "AUTO-MERGE: OFF";
        onboardingLabel.style.color = autoMergeEnabled ? "var(--accent-sage)" : "var(--text-muted)";
    }

    if (dashStatusPill) {
        if (autoMergeEnabled) {
            dashStatusPill.textContent = "Auto-Merge Active";
            dashStatusPill.style.color = "var(--accent-sage)";
            dashStatusPill.style.background = "var(--sage-bg)";
            dashStatusPill.style.borderColor = "var(--sage-border)";
        } else {
            dashStatusPill.textContent = "Manual Review Mode";
            dashStatusPill.style.color = "var(--accent-amber)";
            dashStatusPill.style.background = "var(--amber-bg)";
            dashStatusPill.style.borderColor = "var(--amber-border)";
        }
    }
}

async function onAutoMergeToggleChanged(checked) {
    updateAutoMergeUI(checked);
    const savedRepo = localStorage.getItem("launchpad_portfolio_repo") || "";
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
        showToast(checked ? "Auto-Merge enabled! Verified releases will merge automatically." : "Manual review mode enabled for future releases.");
    } catch (e) {
        console.warn("Failed to persist auto-merge state to server:", e);
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
        showToast("Please enter a valid repo (e.g. username/portfolio or GitHub URL)");
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
    showToast(`Connected ${slug} as target portfolio repo!`);
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

// ── Sidebar Collapse Toggle [ ◀ | ▶ ] ─────────────────────────────────
function toggleDecisionSidebar() {
    const grid = document.getElementById("dash-cockpit-grid");
    const btn = document.getElementById("btn-toggle-sidebar");
    if (!grid || !btn) return;

    const isCollapsed = grid.classList.toggle("sidebar-collapsed");
    btn.textContent = isCollapsed ? "▶" : "◀";
    btn.title = isCollapsed ? "Expand Feed" : "Collapse Feed";
}

let currentAgentExecutionState = "idle"; // "idle" | "running"
let isTerminalExpanded = false;
let lastRunDuration = "";
let currentRunningRepo = "";

// ── Live Terminal Expansion & Decoupled Header State ──────────────────
function renderTerminalHeader() {
    const titleEl = document.getElementById("terminal-status-title");
    const descEl = document.getElementById("terminal-status-desc");
    const dotEl = document.getElementById("terminal-status-dot");
    const toggleBtn = document.getElementById("btn-terminal-toggle");
    const timerBadge = document.getElementById("terminal-timer-badge");
    const stagesContainer = document.getElementById("terminal-stages-collapsible");

    if (currentAgentExecutionState === "running") {
        if (titleEl) titleEl.textContent = "AGENT RUNNING";
        if (descEl) descEl.textContent = currentRunningRepo ? `· Processing ${currentRunningRepo}` : "· Processing GitHub Release";
        if (dotEl) {
            dotEl.style.background = "#22C55E";
            dotEl.className = "dot-indicator pulse";
        }
        if (timerBadge) timerBadge.style.display = "inline-block";
        if (toggleBtn) toggleBtn.textContent = isTerminalExpanded ? "Collapse logs ▴" : "Expand logs ▾";
    } else {
        if (titleEl) titleEl.textContent = "AGENT STANDBY";
        if (descEl) descEl.textContent = lastRunDuration ? `· Last run completed in ${lastRunDuration}` : "· Watching connected GitHub repositories for tagged releases";
        if (dotEl) {
            dotEl.style.background = "#22C55E";
            dotEl.className = "dot-indicator";
        }
        if (timerBadge) timerBadge.style.display = "none";
        if (toggleBtn) toggleBtn.textContent = isTerminalExpanded ? "Collapse logs ▴" : "View execution logs ▾";
    }

    if (stagesContainer) {
        stagesContainer.style.display = isTerminalExpanded ? "block" : "none";
    }
}

function toggleTerminalExpansion() {
    isTerminalExpanded = !isTerminalExpanded;
    renderTerminalHeader();
}

// ── Real-Time Agent Telemetry Polling (/api/agent-status) ────────────
let highestStageSeen = 1;

async function pollAgentStatus() {
    try {
        const resp = await fetch("/api/agent-status");
        if (!resp.ok) return;
        const statusData = await resp.json();

        const timerBadge = document.getElementById("terminal-timer-badge");
        const equalizer = document.getElementById("model-equalizer-bars");

        if (statusData && statusData.status === "running") {
            currentRunningRepo = statusData.repo || "";
            const currentStage = Math.max(statusData.stage || 1, highestStageSeen);
            highestStageSeen = currentStage;

            if (!isAgentCurrentlyRunning) {
                isAgentCurrentlyRunning = true;
                currentAgentExecutionState = "running";
                isTerminalExpanded = true;
                renderTerminalHeader();
                if (equalizer) equalizer.classList.add("pulsing");
            }

            // Real-time server-synchronized timer
            const serverStart = statusData.started_at ? new Date(statusData.started_at).getTime() : Date.now();
            const elapsed = Math.max(0, ((Date.now() - serverStart) / 1000)).toFixed(1);
            if (timerBadge) {
                timerBadge.style.display = "inline-block";
                timerBadge.textContent = `${elapsed}s elapsed`;
            }

            const stageItems = [
                document.getElementById("stage-1"),
                document.getElementById("stage-2"),
                document.getElementById("stage-3"),
                document.getElementById("stage-4"),
                document.getElementById("stage-5"),
                document.getElementById("stage-6")
            ];

            stageItems.forEach((el, idx) => {
                if (!el) return;
                const stageNum = idx + 1;
                if (stageNum < currentStage) {
                    el.className = "terminal-stage-item done";
                } else if (stageNum === currentStage) {
                    el.className = "terminal-stage-item active";
                } else {
                    el.className = "terminal-stage-item pending";
                }
            });
        } else if (isAgentCurrentlyRunning && (!statusData || statusData.status === "idle")) {
            // Finished execution!
            isAgentCurrentlyRunning = false;
            currentAgentExecutionState = "idle";
            highestStageSeen = 1;

            const stageItems = [
                document.getElementById("stage-1"),
                document.getElementById("stage-2"),
                document.getElementById("stage-3"),
                document.getElementById("stage-4"),
                document.getElementById("stage-5"),
                document.getElementById("stage-6")
            ];
            stageItems.forEach(el => {
                if (el) el.className = "terminal-stage-item done";
            });

            if (equalizer) equalizer.classList.remove("pulsing");
            const finalDuration = statusData.duration_seconds
                ? `${statusData.duration_seconds}s`
                : (statusData.started_at && statusData.completed_at
                    ? `${((new Date(statusData.completed_at) - new Date(statusData.started_at)) / 1000).toFixed(1)}s`
                    : "4.5s");
            lastRunDuration = finalDuration;
            renderTerminalHeader();

            // Reload decisions immediately to show the new card & stream post without refresh!
            await loadDecisions();

            // Auto-collapse after 20 seconds
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

// ── Agent Voice Narration Helper ──────────────────────────────────────
function formatAgentVoice(decision) {
    const action = decision.action || "skip";
    const rawReason = decision.reasoning || "";
    const repo = decision.repo || "this project";

    if (rawReason.toLowerCase().startsWith("i evaluated") || rawReason.toLowerCase().startsWith("i looked") || rawReason.toLowerCase().startsWith("i analyzed")) {
        return rawReason;
    }

    if (action === "skip") {
        return `I evaluated the changelog and release diff for ${repo} — dependency updates and minor maintenance only. Nothing here alters your core technical capability, so I preserved your portfolio untouched.`;
    } else if (action === "feature_new") {
        return `I analyzed the codebase and release notes for ${repo}: new capabilities and technical architecture detected. I generated a new project card, synced your skills footprint, and staged your launch announcement.`;
    } else {
        return `I matched ${repo} against your existing portfolio entry. Refreshed the architectural summary, bumped the version line, and updated live deployment links.`;
    }
}

// ── Decision Feed Fetching & Rendering ────────────────────────────────
async function loadDecisions() {
    try {
        const resp = await fetch("/api/decisions");
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const decisions = await resp.json();

        if (decisions && decisions.length > 0) {
            const latest = decisions[0];
            const latestId = latest.delivery_id || latest.id || (latest.repo + "_" + (latest.tag || "") + "_" + (latest.ts || ""));

            if (lastSeenDecisionId && lastSeenDecisionId !== latestId) {
                // A new release arrived! Select it and trigger typewriter stream
                selectedDeliveryId = latestId;
                allDecisions = decisions;
                renderDecisions(decisions);
                streamPostText(latest, true);
            } else if (!selectedDeliveryId) {
                // Initial load
                selectedDeliveryId = latestId;
                allDecisions = decisions;
                renderDecisions(decisions);
                renderActivePostWorkspace(latest, false);
            } else {
                allDecisions = decisions;
                renderDecisions(decisions);
            }
            lastSeenDecisionId = latestId;
        } else {
            allDecisions = [];
            renderDecisions([]);
        }
    } catch (err) {
        console.error("Failed to fetch decisions:", err);
    }
}

function renderDecisions(decisions) {
    const container = document.getElementById("decision-log");
    const emptyState = document.getElementById("decision-log-empty");
    const countPill = document.getElementById("nav-decisions-count");

    if (!decisions || decisions.length === 0) {
        emptyState.style.display = "block";
        if (countPill) countPill.textContent = "0";
        return;
    }

    emptyState.style.display = "none";
    if (countPill) countPill.textContent = decisions.length.toString();

    // Update last sync time
    const syncText = document.getElementById("dash-last-event-text");
    if (syncText && decisions[0] && decisions[0].ts) {
        syncText.textContent = formatRelativeTime(decisions[0].ts);
    }

    container.innerHTML = "";

    decisions.forEach(d => {
        const docKey = d.delivery_id || d.id || (d.repo + "_" + (d.tag || "") + "_" + (d.ts || ""));
        const isSelected = selectedDeliveryId === docKey || (!selectedDeliveryId && decisions[0] === d);
        const item = document.createElement("div");
        item.className = `decision-row-item decision-card-item ${isSelected ? "selected" : ""}`;
        item.onclick = () => selectDecision(docKey);

        const action = d.action || "skip";
        const badgeClass = `badge-${action}`;
        const tsFormatted = d.ts ? formatTimestamp(d.ts) : "";
        const repo = d.repo || "unknown/repo";
        const tag = d.tag ? `v${d.tag.replace(/^v/, "")}` : "";
        const voiceNarrative = formatAgentVoice(d);
        const artifacts = d.artifacts || {};
        const isAutoMerged = artifacts.portfolio_pr_merged;

        // Auto-Merged Celebration Banner or Skip Restraint
        let bannerHtml = "";
        if (action !== "skip" && isAutoMerged) {
            const prUrl = artifacts.portfolio_pr || "#";
            bannerHtml = `
                <div class="hero-moment-banner auto-merged font-mono-lp">
                    <span>✨ Live Portfolio Updated</span>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <a href="${escapeHtml(prUrl)}" target="_blank" rel="noopener" style="color:var(--accent-sage); font-weight:700; text-decoration:underline;">PR Merged ✓</a>
                    </div>
                </div>
            `;
        } else if (action === "skip") {
            bannerHtml = `
                <div class="hero-moment-banner skipped font-mono-lp">
                    <span>🛡️ Assessed: Not portfolio-notable · Preserved</span>
                </div>
            `;
        } else if (artifacts.portfolio_pr) {
            bannerHtml = `
                <div class="hero-moment-banner skipped font-mono-lp" style="background:#FFFBEB; border-color:#FDE68A; color:#92400E;">
                    <span>📄 Review PR: <a href="${escapeHtml(artifacts.portfolio_pr)}" target="_blank" rel="noopener" style="color:#92400E; font-weight:700; text-decoration:underline;">Open PR ↗</a></span>
                </div>
            `;
        }

        // PR & Action Pills
        let prPill = "";
        if (action === "skip") {
            prPill = `<span class="badge-pill font-mono-lp" style="background:#F1F5F9; color:#475569; border-color:#CBD5E1;">🛡️ PRESERVED</span>`;
        } else if (isAutoMerged) {
            const prUrl = artifacts.portfolio_pr || "#";
            prPill = `<a href="${escapeHtml(prUrl)}" target="_blank" rel="noopener" class="badge-pill font-mono-lp" style="background:var(--sage-bg); color:var(--accent-sage); border-color:var(--sage-border);" onclick="event.stopPropagation();">🖼️ PR AUTO-MERGED</a>`;
        } else if (artifacts.portfolio_pr) {
            prPill = `<a href="${escapeHtml(artifacts.portfolio_pr)}" target="_blank" rel="noopener" class="badge-pill font-mono-lp" style="background:var(--amber-bg); color:var(--accent-amber); border-color:var(--amber-border);" onclick="event.stopPropagation();">🖼️ OPEN PR # ↗</a>`;
        }

        item.innerHTML = `
            <div class="decision-row-top" style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">
                <div class="decision-repo-title" style="display:flex; align-items:center; gap:6px; font-weight:600;">
                    <span>${escapeHtml(repo)}</span>
                    ${tag ? `<span class="decision-version-tag font-mono-lp">${escapeHtml(tag)}</span>` : ""}
                </div>
                <span class="decision-meta-time font-mono-lp" style="font-size:11px; color:var(--text-muted);">${escapeHtml(tsFormatted)}</span>
            </div>
            <div class="decision-row-body">
                <div class="decision-badges-wrap" style="display:flex; align-items:center; gap:6px; margin-bottom:6px; flex-wrap:wrap;">
                    <span class="decision-badge font-mono-lp ${badgeClass}">${escapeHtml(action.toUpperCase())}</span>
                    ${prPill}
                </div>
                ${bannerHtml}
                <div class="agent-narrative-box">
                    "${escapeHtml(voiceNarrative)}"
                </div>
            </div>
        `;

        container.appendChild(item);
    });
}

function selectDecision(deliveryId) {
    selectedDeliveryId = deliveryId;
    renderDecisions(allDecisions);
    const target = allDecisions.find(d => (d.delivery_id || d.id || (d.repo + "_" + (d.tag || "") + "_" + (d.ts || ""))) === deliveryId);
    if (target) {
        renderActivePostWorkspace(target, false);
    }
}

// ── Token-by-Token Streaming Typewriter ────────────────────────────────
function streamPostText(decision, isLiveStream) {
    renderActivePostWorkspace(decision, isLiveStream);
}

function renderActivePostWorkspace(decision, shouldAnimateTypewriter) {
    const empty = document.getElementById("post-card-empty");
    const content = document.getElementById("post-card-content");
    const repoEl = document.getElementById("post-repo");
    const badge = document.getElementById("post-action-badge");
    const textEl = document.getElementById("post-text");
    const reasoningEl = document.getElementById("post-reasoning");
    const imgContainer = document.getElementById("post-image-container");
    const imgEl = document.getElementById("post-image");
    const hashtagsEl = document.getElementById("post-hashtags");
    const linksEl = document.getElementById("post-links");
    const footnoteEl = document.getElementById("quiet-next-build-footnote");

    if (!decision) {
        if (empty) empty.style.display = "block";
        if (content) content.style.display = "none";
        return;
    }

    if (empty) empty.style.display = "none";
    if (content) content.style.display = "block";

    currentPostPackage = decision;
    const artifacts = decision.artifacts || {};
    const pkg = artifacts.post_package || {};
    const action = decision.action || "skip";

    // Repo title & action badge
    if (repoEl) repoEl.textContent = `${decision.repo || ""} ${decision.tag ? `v${decision.tag.replace(/^v/, "")}` : ""}`;
    if (badge) {
        badge.style.display = "inline-block";
        badge.textContent = action.toUpperCase();
        badge.className = `decision-badge font-mono-lp badge-${action}`;
    }

    const actionBtnGroup = document.getElementById("post-action-btn-group");
    const restraintBadge = document.getElementById("post-restraint-badge");

    // Handle SKIP decision state
    if (action === "skip" || !pkg.text) {
        if (actionBtnGroup) actionBtnGroup.style.display = "none";
        if (restraintBadge) restraintBadge.style.display = "inline-block";
        if (reasoningEl) reasoningEl.style.display = "none"; // Hide empty green border
        if (textEl) {
            textEl.innerHTML = `
                <div style="padding:20px; background:var(--bg-surface-elevated); border:1px solid var(--border-base); border-radius:6px; color:var(--text-secondary);">
                    <strong style="color:var(--text-primary); display:block; margin-bottom:8px; font-size:14px;">🛡️ Autonomous Editorial Restraint</strong>
                    This release was assessed as maintenance/dependency updates only. To protect your professional audience from noise and keep your portfolio high-signal, no LinkedIn launch post was drafted and no code changes were committed to your live site.
                </div>
            `;
        }
        if (imgContainer) imgContainer.style.display = "none";
        if (hashtagsEl) hashtagsEl.innerHTML = "";
        if (linksEl) linksEl.innerHTML = "";
        if (footnoteEl) footnoteEl.style.display = "none";
        return;
    }

    // Active Feature/Update state
    if (actionBtnGroup) actionBtnGroup.style.display = "flex";
    if (restraintBadge) restraintBadge.style.display = "none";
    if (reasoningEl) {
        reasoningEl.style.display = "block";
        reasoningEl.textContent = `"${formatAgentVoice(decision)}"`;
    }

    // Body Text with Token Typewriter or Instant Render
    const fullText = pkg.text || "";
    if (activeStreamInterval) clearInterval(activeStreamInterval);

    if (shouldAnimateTypewriter) {
        textEl.textContent = "";
        const cursor = document.createElement("span");
        cursor.className = "typewriter-cursor";
        cursor.textContent = "▌";
        textEl.appendChild(cursor);

        const words = fullText.split(" ");
        let wordIdx = 0;

        activeStreamInterval = setInterval(() => {
            if (wordIdx < words.length) {
                const currentText = words.slice(0, wordIdx + 1).join(" ");
                textEl.innerHTML = escapeHtml(currentText) + `<span class="typewriter-cursor">▌</span>`;
                wordIdx++;
            } else {
                clearInterval(activeStreamInterval);
                textEl.innerHTML = escapeHtml(fullText);
                fadeInPostMedia(pkg, artifacts, decision);
            }
        }, 35);
    } else {
        textEl.innerHTML = escapeHtml(fullText);
        fadeInPostMedia(pkg, artifacts, decision);
    }
}

function fadeInPostMedia(pkg, artifacts, decision) {
    const imgContainer = document.getElementById("post-image-container");
    const imgEl = document.getElementById("post-image");
    const hashtagsEl = document.getElementById("post-hashtags");
    const linksEl = document.getElementById("post-links");
    const footnoteEl = document.getElementById("quiet-next-build-footnote");

    // UI Snapshot Banner
    if (pkg.image_url) {
        imgEl.src = pkg.image_url;
        imgContainer.style.display = "block";
    } else {
        imgContainer.style.display = "none";
    }

    // Hashtags
    hashtagsEl.innerHTML = "";
    if (pkg.hashtags && pkg.hashtags.length > 0) {
        pkg.hashtags.forEach(tag => {
            const chip = document.createElement("span");
            chip.className = "post-hashtag-chip font-mono-lp";
            chip.textContent = tag.startsWith("#") ? tag : `#${tag}`;
            hashtagsEl.appendChild(chip);
        });
    }

    // PR Links
    linksEl.innerHTML = "";
    if (artifacts.portfolio_pr) {
        const mergedBadge = artifacts.portfolio_pr_merged ? "✓ AUTO-MERGED" : "OPEN ↗";
        linksEl.innerHTML += `
            <a class="pr-link-chip font-mono-lp" href="${escapeHtml(artifacts.portfolio_pr)}" target="_blank" rel="noopener" style="font-weight:600;">
                🖼️ Portfolio PR [${mergedBadge}]
            </a>
        `;
    }
    if (artifacts.readme_pr) {
        linksEl.innerHTML += `
            <a class="pr-link-chip font-mono-lp" href="${escapeHtml(artifacts.readme_pr)}" target="_blank" rel="noopener">
                📄 README PR ↗
            </a>
        `;
    }

    // Quiet 1-Line Next Build Footnote (Aditi Demotion)
    const nextBuilds = (artifacts && artifacts.next_builds) || decision.next_builds || [];
    if (nextBuilds && nextBuilds.length > 0) {
        const firstRec = nextBuilds[0];
        const recTitle = firstRec.title || firstRec.text || firstRec.name || "";
        const recReason = firstRec.one_line_reason || firstRec.reason || "";
        if (recTitle || recReason) {
            footnoteEl.style.display = "block";
            footnoteEl.innerHTML = `💡 <strong>Next Build Suggestion:</strong> <em>${escapeHtml(recTitle)}</em>${recReason ? ` — ${escapeHtml(recReason)}` : ""}`;
        } else {
            footnoteEl.style.display = "none";
        }
    } else {
        footnoteEl.style.display = "none";
    }
}

// ── Copy Post & Open LinkedIn ─────────────────────────────────────────
function copyPostContent() {
    if (!currentPostPackage) {
        showToast("No active post draft to copy.");
        return;
    }

    const artifacts = currentPostPackage.artifacts || {};
    const pkg = artifacts.post_package || {};
    const text = pkg.text || "";
    const hashtags = (pkg.hashtags || []).map(t => t.startsWith("#") ? t : `#${t}`).join(" ");
    const fullContent = hashtags ? `${text}\n\n${hashtags}` : text;

    navigator.clipboard.writeText(fullContent).then(() => {
        showToast("Copied launch post! Opening LinkedIn composer...");
        const btn = document.getElementById("btn-copy");
        if (btn) {
            btn.textContent = "✓ Copied to clipboard!";
            btn.classList.add("copied");
            setTimeout(() => {
                btn.textContent = "📋 Copy post & Open LinkedIn";
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
        showToast("🖼️ Image copied to clipboard! Paste directly into LinkedIn.");
    } catch (err) {
        console.warn("Direct blob clipboard write failed, opening image URL:", err);
        window.open(imageUrl, "_blank");
        showToast("Opened full resolution image in new tab.");
    }
}

function editPostContent() {
    const textEl = document.getElementById("post-text");
    const btn = document.getElementById("btn-edit-post");
    if (!textEl) return;

    const isEditing = textEl.getAttribute("contenteditable") === "true";
    if (isEditing) {
        textEl.setAttribute("contenteditable", "false");
        textEl.style.border = "none";
        if (btn) btn.textContent = "Edit";
        showToast("Draft updated!");
    } else {
        textEl.setAttribute("contenteditable", "true");
        textEl.focus();
        textEl.style.border = "1px solid var(--accent-sage)";
        textEl.style.padding = "8px";
        textEl.style.borderRadius = "4px";
        if (btn) btn.textContent = "Save";
        showToast("You can now edit the post draft directly.");
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

    // Initial data fetch
    loadDecisions();
    pollAgentStatus();

    // Real-time telemetry polling (every 350ms for instant live streaming updates)
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
