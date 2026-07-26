let runStartedAt = null;
let timerInterval = null;
let lastStatus = "IDLE";
let approvedScriptFile = null;
let buildInFlight = false;
let sawFreshBuildStatus = false;
let analyzeFlowMode = null;

const QUOTES = [
    { text: "Here's looking at you, kid.", attr: "— Casablanca", type: "SCREENPLAY" },
    { text: "I'm gonna make him an offer he can't refuse.", attr: "— The Godfather", type: "SCREENPLAY" },
    { text: "You can't handle the truth!", attr: "— A Few Good Men", type: "SCREENPLAY" },
    { text: "Get busy living, or get busy dying.", attr: "— The Shawshank Redemption", type: "SCREENPLAY" },
    { text: "The stuff that dreams are made of.", attr: "— The Maltese Falcon", type: "SCREENPLAY" },
    { text: "Keep your friends close, but your enemies closer.", attr: "— The Godfather Part II", type: "SCREENPLAY" },
    { text: "Every passing minute is another chance to turn it all around.", attr: "— Vanilla Sky", type: "SCREENPLAY" },
    { text: "After all, tomorrow is another day.", attr: "— Gone with the Wind", type: "SCREENPLAY" },
    { text: "It ain't about how hard you hit. It's about how hard you can get hit and keep moving forward.", attr: "— Rocky Balboa", type: "SCREENPLAY" },
    { text: "They may take our lives, but they'll never take our freedom!", attr: "— Braveheart", type: "SCREENPLAY" },
    { text: "Why so serious?", attr: "— The Dark Knight", type: "SCREENPLAY" },
    { text: "To infinity and beyond.", attr: "— Toy Story", type: "SCREENPLAY" },
    { text: "Nobody puts Baby in a corner.", attr: "— Dirty Dancing", type: "SCREENPLAY" },
    { text: "You is kind, you is smart, you is important.", attr: "— The Help", type: "SCREENPLAY" },
    { text: "I feel the need — the need for speed!", attr: "— Top Gun", type: "SCREENPLAY" },
    { text: "Speed!", attr: "— Camera rolling", type: "ON SET" },
    { text: "Quiet on set!", attr: "— First AD", type: "ON SET" },
    { text: "Picture's up!", attr: "— Ready to roll", type: "ON SET" },
    { text: "That's a wrap.", attr: "— End of shoot", type: "ON SET" },
    { text: "We'll fix it in post.", attr: "— Universal set truth", type: "ON SET" },
    { text: "Check the gate.", attr: "— After every take", type: "ON SET" },
    { text: "Martini shot.", attr: "— Last shot of the day", type: "ON SET" },
    { text: "Back to one.", attr: "— Reset", type: "ON SET" },
    { text: "Crafty is open.", attr: "— The most important announcement", type: "ON SET" },
    { text: "Talent on set.", attr: "— Here they come", type: "ON SET" },
    { text: "That's a company move.", attr: "— Packing up", type: "ON SET" },
    { text: "Lunch is up!", attr: "— The call everyone waits for", type: "ON SET" },
];

let quoteInterval = null;
let quoteIndex = Math.floor(Math.random() * QUOTES.length);

function showNextQuote(){
    const textEl = document.getElementById("quoteText");
    const attrEl = document.getElementById("quoteAttribution");
    const labelEl = document.getElementById("quoteLabel");
    if (!textEl) return;
    textEl.style.opacity = "0";
    attrEl.style.opacity = "0";
    setTimeout(() => {
        quoteIndex = (quoteIndex + 1) % QUOTES.length;
        const q = QUOTES[quoteIndex];
        textEl.textContent = "\u201C" + q.text + "\u201D";
        attrEl.textContent = q.attr;
        labelEl.textContent = q.type;
        textEl.style.opacity = "1";
        attrEl.style.opacity = "1";
    }, 600);
}

function startQuoteRotation(){
    showNextQuote();
    quoteInterval = setInterval(showNextQuote, 7000);
}

function stopQuoteRotation(){
    if (quoteInterval) { clearInterval(quoteInterval); quoteInterval = null; }
}
let progressValue = 0;
let progressInterval = null;
let infoModalAction = null;
let activeCompleteView = "preview";
let latestSlidesLoadedForComplete = false;

const fallbackSlides = [
    {
        type: "Title Slide",
        title: "COURT JESTER",
        subtitle: "Animated fantasy comedy with heart, music moments, and chaos.",
        body: "A gifted misfit stumbles into the royal court and becomes the most dangerous fool in the kingdom.",
        caption: "Preview of the currently selected placeholder slide.",
        accent: "#ffb347"
    },
    {
        type: "Logline",
        title: "Logline",
        subtitle: "The one-line pitch",
        body: "When a sharp-tongued outsider is pulled into palace politics, he must outwit enemies, protect the kingdom, and prove that laughter can be a weapon.",
        caption: "Placeholder logline slide preview.",
        accent: "#ff9955"
    },
    {
        type: "Synopsis",
        title: "Synopsis",
        subtitle: "Story overview",
        body: "The Understudy follows a clever survivor who becomes an unexpected player inside a kingdom full of secrets, danger, and spectacle.",
        caption: "Placeholder synopsis slide preview.",
        accent: "#ffc266"
    },
    {
        type: "Characters",
        title: "Main Characters",
        subtitle: "Core ensemble",
        body: "The Jester, the Princess, the Shadow Adviser, and the King each drive a different part of the conflict.",
        caption: "Placeholder characters slide preview.",
        accent: "#ff9c3d"
    },
    {
        type: "Why This Project",
        title: "Why This Project",
        subtitle: "Tone + audience + hook",
        body: "The Understudy blends spectacle, comedy, and emotional storytelling into a world that can support franchise thinking.",
        caption: "Placeholder closing slide preview.",
        accent: "#ffcf70"
    }
];

let refineSlides = JSON.parse(JSON.stringify(fallbackSlides));
let latestRefineProjectTitle = "UNTITLED PROJECT";
let currentRefineSlide = 0;
let currentImageOptionModalIndex = 0;
const BASE_PATH_PREFIX = window.BASE_PATH_PREFIX || "";

function enterFlowMode(){
    document.body.classList.add("flow-mode");
}
function exitFlowMode(){
    document.body.classList.remove("flow-mode");
}
function enterActiveBuildMode(){
    document.body.classList.add("active-build");
}
function exitActiveBuildMode(){
    document.body.classList.remove("active-build");
    document.body.classList.remove("complete-mode");
}
function setProgress(value){
    progressValue = Math.max(0, Math.min(100, value));
    const fill = document.getElementById("progressFill");
    if (fill) fill.style.width = progressValue + "%";
}

function stopProgressCreep(){
    if (progressInterval){
        clearInterval(progressInterval);
        progressInterval = null;
    }
}

function startProgressCreep(target, step, delay){
    stopProgressCreep();
    progressInterval = setInterval(() => {
        if (progressValue >= target){
            stopProgressCreep();
            return;
        }
        setProgress(progressValue + step);
    }, delay);
}

function updateProgressForStatus(status){
    if (status === "IDLE"){
        stopProgressCreep();
        setProgress(0);
    } else if (status === "UPLOADED"){
        setProgress(Math.max(progressValue, 12));
        startProgressCreep(22, 1, 500);
    } else if (status === "ANALYZING"){
        setProgress(Math.max(progressValue, 38));
        startProgressCreep(68, 1.2, 700);
    } else if (status === "BUILDING"){
        setProgress(Math.max(progressValue, 78));
        startProgressCreep(96, 1, 500);
    } else if (status === "DEMO_RUNNING"){
        setProgress(Math.max(progressValue, 20));
        startProgressCreep(60, 1, 650);
    } else if (status === "COMPLETE"){
        stopProgressCreep();
        setProgress(100);
    } else if (status === "ERROR"){
        stopProgressCreep();
    }
}

function startAnalyzeFlow(){
    analyzeFlowMode = "analyze";
    resetCreateProject();
    showUploadAnalyzeModal();
}

function startUploadFlow(){
    analyzeFlowMode = "upload";
    resetCreateProject();
    showUploadAnalyzeModal();
}

function hideWorkspacePanels(){
    document.getElementById("analyzerPanel").style.display = "none";
    document.getElementById("uploadState").style.display = "none";
    document.getElementById("ideaPanel").style.display = "none";
}

function resumeUploadAfterInfo(){
    closeModal("infoModal");
    infoModalAction = null;
    document.getElementById("uploadModal").classList.add("show");
}

function closeModal(id){
    const el = document.getElementById(id);
    if (el) el.classList.remove("show");
}


let selectedFeedbackType = "";

function toggleTopNavMenu(){
    const menu = document.getElementById("topNavMenu");
    if (!menu) return;
    menu.classList.toggle("show");
}
document.addEventListener("click", function(event){
    const shell = document.querySelector(".top-nav-shell");
    const menu = document.getElementById("topNavMenu");
    if (!shell || !menu) return;
    if (!shell.contains(event.target)){
        menu.classList.remove("show");
    }
});

function openFeedbackModal(){
    const menu = document.getElementById("topNavMenu");
    if (menu) menu.classList.remove("show");
    document.getElementById("feedbackModal").classList.add("show");
}
function openContactModal(){
    const menu = document.getElementById("topNavMenu");
    if (menu) menu.classList.remove("show");
    document.getElementById("contactModal").classList.add("show");
}
function openPrivacyModal(){
    const menu = document.getElementById("topNavMenu");
    if (menu) menu.classList.remove("show");
    document.getElementById("privacyModal").classList.add("show");
}
async function submitContact(){
    const name = (document.getElementById("contactName").value || "").trim();
    const email = (document.getElementById("contactEmail").value || "").trim();
    const message = (document.getElementById("contactMessage").value || "").trim();
    if (!message){ showInfoModal("Contact", "Please write a message before sending."); return; }
    try {
        const resp = await fetch("/contact", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name, email, message})
        });
        const data = await resp.json();
        closeModal("contactModal");
        document.getElementById("contactName").value = "";
        document.getElementById("contactEmail").value = "";
        document.getElementById("contactMessage").value = "";
        showInfoModal("Message Sent", "Thanks for reaching out. We'll get back to you soon.");
    } catch(e) {
        showInfoModal("Contact", "Something went wrong. Please try again.");
    }
}
function setFeedbackType(type, el){
    selectedFeedbackType = type;
    document.querySelectorAll(".feedback-chip").forEach(btn => btn.classList.remove("active"));
    if (el) el.classList.add("active");
}
function submitFeedback(){
    const name = (document.getElementById("feedbackName") || {}).value || "";
    const email = (document.getElementById("feedbackEmail") || {}).value || "";
    const message = (document.getElementById("feedbackMessage") || {}).value || "";

    if (!message.trim()) {
        alert("Please enter a message before submitting.");
        return;
    }

    fetch("/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: selectedFeedbackType, name, email, message })
    });

    closeModal("feedbackModal");
    showInfoModal("Feedback Received", "Thanks — your beta feedback has been captured for review.");

    const logEl = document.getElementById("liveProcessLog");
    if (logEl){
        const payload = [selectedFeedbackType, name, message].filter(Boolean).join(" | ");
        logEl.innerHTML += "<br><span class=\"terminal-success\">[feedback]</span> " + payload.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
    }

    selectedFeedbackType = "";
    document.querySelectorAll(".feedback-chip").forEach(btn => btn.classList.remove("active"));
    if (document.getElementById("feedbackName")) document.getElementById("feedbackName").value = "";
    if (document.getElementById("feedbackEmail")) document.getElementById("feedbackEmail").value = "";
    if (document.getElementById("feedbackMessage")) document.getElementById("feedbackMessage").value = "";
}
    function downloadCurrentDeck(){
    if (window.latestGeneratedDeck){
        window.location.href = "/output-file?name=" + encodeURIComponent(window.latestGeneratedDeck);
        return;
    }
    window.location.href = "/download/latest.pptx";
}

function closeAllModals(){
    closeModal("loginModal");
    closeModal("infoModal");
    closeModal("uploadModal");
    closeModal("uploadPassModal");
    closeModal("analyzeFailModal");
    closeModal("analyzePassModal");
    closeModal("actorPrepModal");
    closeModal("actorPrepPasteModal");
    closeModal("actorPrepPassModal");
    closeModal("actorBookedModal");
    closeModal("actorBookedPasteModal");
    closeModal("actorBookedCompleteModal");
    closeModal("feedbackModal");
}

function showInfoModal(title, copy, action = null, buttonLabel = "Continue"){
    document.getElementById("infoTitle").textContent = title;
    document.getElementById("infoCopy").textContent = copy;
    infoModalAction = action;
    const btn = document.getElementById("infoModalActionButton");
    if (btn) btn.textContent = buttonLabel;
    document.getElementById("infoModal").classList.add("show");
}

function handleInfoModalAction(){
    closeModal("infoModal");
    if (typeof infoModalAction === "function"){
        const fn = infoModalAction;
        infoModalAction = null;
        fn();
    } else {
        infoModalAction = null;
    }
}

function showUploadState(){
    exitActiveBuildMode();
    enterFlowMode();
    hideWorkspacePanels();

    const homeCardGrid = document.querySelector(".home-card-grid");
    const choicesRow = document.querySelector(".choices-row");
    const uploadState = document.getElementById("uploadState");

    if (homeCardGrid) homeCardGrid.style.display = "none";
    if (choicesRow) choicesRow.style.display = "none";
    if (uploadState) uploadState.style.display = "block";
}

function resetCreateProject(){
    closeAllModals();
    stopProgressCreep();
    setProgress(0);
    exitActiveBuildMode();
    exitFlowMode();
    hideWorkspacePanels();

    approvedScriptFile = null;
    buildInFlight = false;
    sawFreshBuildStatus = false;
    activeCompleteView = "preview";
    currentRefineSlide = 0;
    latestSlidesLoadedForComplete = false;

    const approvedScriptBox = document.getElementById("approvedScriptBox");
    const approvedScriptName = document.getElementById("approvedScriptName");
    const imagesInput = document.getElementById("imagesInput");
    const posterInput = document.getElementById("posterInput");
    const homeCardGrid = document.querySelector(".home-card-grid");
    const choicesRow = document.querySelector(".choices-row");

    if (approvedScriptBox) approvedScriptBox.style.display = "none";
    if (approvedScriptName) approvedScriptName.textContent = "-";
    if (imagesInput) imagesInput.value = "";
    if (posterInput) posterInput.value = "";
    if (homeCardGrid) homeCardGrid.style.display = "block";
    if (choicesRow) choicesRow.style.display = "grid";

    document.getElementById("liveProcessLog").style.display = "block";
    document.getElementById("buildMeta").style.display = "none";
    document.getElementById("buildCopy").style.display = "block";
    document.getElementById("completePanel").style.display = "none";
    const previewStage = document.getElementById("previewStage");
    const refinementStage = document.getElementById("refinementStage");
    if (previewStage) previewStage.style.display = "block";
    if (refinementStage) refinementStage.style.display = "none";

    showUploadAnalyzeModal();
}

function showUploadAnalyzeModal(){
    document.getElementById("uploadModal").classList.add("show");
}

function openAnalyzePassModal(){
    closeAllModals();
    document.getElementById("analyzePassModal").classList.add("show");
}

function continueToApprovedUpload(){
    closeAllModals();
    showUploadState();

    const scriptInput = document.getElementById("scriptInput");

    if (approvedScriptFile && scriptInput) {
        try {
            const dt = new DataTransfer();
            dt.items.add(approvedScriptFile);
            scriptInput.files = dt.files;
        } catch (e) {}
    }
}

async function analyzeSelectedScript(){
    const fileInput = document.getElementById("uploadAnalyzeFile");

    if (!fileInput || !fileInput.files || fileInput.files.length === 0){
        closeModal("uploadModal");
        document.getElementById("infoTitle").textContent = "Upload Script";
        document.getElementById("infoCopy").textContent = "Please choose a script file before continuing.";
        document.getElementById("infoModal").classList.add("show");
        return;
    }

    const file = fileInput.files[0];
    const fileName = (file.name || "").toLowerCase();
    const passes = fileName.endsWith(".txt") || fileName.endsWith(".pdf") || fileName.endsWith(".fdx") || fileName.endsWith(".docx") || fileName.endsWith(".doc");

    if (!passes){
        closeModal("uploadModal");
        showInfoModal("Unsupported File", "Please upload a TXT, PDF, FDX, or DOCX file.");
        return;
    }

    closeModal("uploadModal");

    // Show progress modal
    const progressModal = document.getElementById("buildProgressModal");
    document.getElementById("buildProgressTitle").textContent = "Analyzing Your Script";
    document.getElementById("buildProgressCopy").textContent = "The Developum AI Engine is reading your script. This takes about 30–60 seconds.";
    document.getElementById("buildProgressStage").textContent = "Analyzing script with Developum AI Engine…";
    document.getElementById("buildProgressFill").style.width = "35%";
    document.getElementById("buildProgressWorking").style.display = "block";
    document.getElementById("buildProgressActions").style.display = "none";
    progressModal.classList.add("show");

    const formData = new FormData();
    formData.append("script", file);

    try {
        const response = await fetch("/analyze-script-pass", {
            method: "POST",
            body: formData
        });

        if (!response.ok){
            document.getElementById("buildProgressWorking").style.display = "none";
            document.getElementById("buildProgressTitle").textContent = "Analysis Failed";
            document.getElementById("buildProgressCopy").textContent = "Something went wrong. Please check your file and try again.";
            const actionsEl = document.getElementById("buildProgressActions");
            actionsEl.style.display = "flex";
            actionsEl.querySelector("button").textContent = "Close";
            actionsEl.querySelector("button").onclick = closeBuildProgressModal;
            return;
        }

        const data = await response.json();
        window.latestGeneratedDeck = data.deck || "";

        const summaryEl = document.getElementById("analysisSummaryCopy");
        if (summaryEl) {
            summaryEl.textContent =
                data.summary_note ||
                "Your script has been analyzed and your full report is ready to view.";
        }

        document.getElementById("buildProgressFill").style.width = "100%";
        document.getElementById("buildProgressWorking").style.display = "none";
        document.getElementById("buildProgressTitle").textContent = "Analysis Complete";
        document.getElementById("buildProgressCopy").textContent = "Your script has been analyzed by the Developum AI Engine.";
        const actionsEl = document.getElementById("buildProgressActions");
        actionsEl.style.display = "flex";

        if (analyzeFlowMode === "analyze") {
            actionsEl.querySelector("button").textContent = "View Results";
            actionsEl.querySelector("button").onclick = function(){
                closeBuildProgressModal();
                openAnalyzePassModal();
            };
        } else {
            approvedScriptFile = file;
            closeBuildProgressModal();
            continueToApprovedUpload();
        }

    } catch (err) {
        document.getElementById("buildProgressWorking").style.display = "none";
        document.getElementById("buildProgressTitle").textContent = "Analysis Failed";
        document.getElementById("buildProgressCopy").textContent = "Something went wrong. Please try again.";
        const actionsEl = document.getElementById("buildProgressActions");
        actionsEl.style.display = "flex";
        actionsEl.querySelector("button").textContent = "Close";
        actionsEl.querySelector("button").onclick = closeBuildProgressModal;
    }
}

function validateUploadAndStart(){
    const form = document.querySelector('#uploadState form');
    const imagesInput = document.getElementById("imagesInput");

    if (imagesInput && imagesInput.files && imagesInput.files.length > 10){
        showInfoModal("Upload Images", "Please upload no more than 10 images.");
        return false;
    }

    if (imagesInput && imagesInput.files){
        for (const file of imagesInput.files){
            if (file.size > 1024 * 1024){
                showInfoModal("Upload Images", "Each image must be 1 MB or smaller.");
                return false;
            }
        }
    }

    buildInFlight = true;
    sawFreshBuildStatus = false;
    showLiveProcess();
    setLocalStatus("UPLOADED");

    const formData = new FormData(form);

    fetch("/upload", {
        method: "POST",
        body: formData
    }).catch(err => {
        console.error("Upload failed:", err);
    });

    return false;
}

function showLiveProcess(){
    exitFlowMode();
    enterActiveBuildMode();
    hideWorkspacePanels();
    stopProgressCreep();
    setProgress(0);

    const homeCardGrid = document.querySelector(".home-card-grid");
    const choicesRow = document.querySelector(".choices-row");
    if (homeCardGrid) homeCardGrid.style.display = "none";
    if (choicesRow) choicesRow.style.display = "none";

    document.getElementById("analyzerPanel").style.display = "block";
    document.getElementById("buildProgressBar").style.display = "block";
    document.getElementById("liveProcessLog").style.display = "block";
    document.getElementById("buildCopy").style.display = "block";
    document.getElementById("buildMeta").style.display = "flex";
    document.getElementById("completePanel").style.display = "none";
    document.body.classList.remove("complete-mode");
    startQuoteRotation();
}

function escapeHtml(text){
    return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function renderLiveProcessLog(status){
    const logEl = document.getElementById("liveProcessLog");
    if (!logEl) return;

    let lines = [];
    if (status === "IDLE"){
        lines = ['[system] waiting for deck generation...','','> pipeline idle','> upload a script and click Generate Deck to begin'];
    } else if (status === "UPLOADED"){
        lines = ['[system] build request received','','> intake: screenplay file accepted','> preparing canonical input','> initializing pipeline environment','> waiting for analysis stage...'];
    } else if (status === "ANALYZING" || status === "running"){
        lines = ['[system] Analyzing Screenplay...','','> converting script into engine-ready format','> cleaning screenplay content','> sending story into brain pass','> extracting characters','> identifying world and tone','> generating pitch intelligence','> analysis still running...'];
    } else if (status === "BUILDING"){
        lines = [
            '[system] deck generation in progress',
            '',
            '> analysis approved',
            '> creating slide plan',
            '> selecting visual placements',
            '> assembling presentation structure',
            '> building PowerPoint file',
            '> finalizing export package...',
            '> preparing delivery...'
        ];
    } else if (status === "DEMO_RUNNING"){
        lines = ['[system] demo build launched','','> loading demo screenplay','> initializing demo pipeline','> analysis queue started','> waiting for deck assembly...'];
    } else if (status === "COMPLETE"){
        lines = ['[system] build complete','','> screenplay processed successfully','> analysis complete','> deck assembly complete','> PowerPoint export ready','','[success] preview ready'];
    } else if (status === "ERROR"){
        lines = ['[system] pipeline interrupted','','> build error detected','> story analysis may be incomplete','> deck assembly may have stopped early','> check terminal / backend logs for details'];
    } else {
        lines = ['[system] processing...','','> pipeline active'];
    }

    const html = lines.map((line) => {
        const safe = escapeHtml(line);
        if (line.startsWith('[success]')) return '<span class="terminal-success">' + safe + '</span>';
        if (line.startsWith('[system]')) return '<span class="terminal-prompt">' + safe + '</span>';
        if (line.startsWith('>')) return '<span class="terminal-accent">' + safe + '</span>';
        return safe;
    }).join('<br>')

    logEl.innerHTML = html;
    logEl.scrollTop = logEl.scrollHeight;
}

function setLocalStatus(status){
    updateStatusUI(status);
}

function formatElapsed(seconds){
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
}

function startTimer(){
    if (!runStartedAt){ runStartedAt = Date.now(); }
    if (timerInterval){ return; }
    timerInterval = setInterval(() => {
        if (!runStartedAt) return;
        const elapsedSeconds = Math.floor((Date.now() - runStartedAt) / 1000);
        const formatted = formatElapsed(elapsedSeconds);
        document.getElementById("inlineStatusValue").textContent = lastStatus + " • " + formatted;
    }, 250);
}

function stopTimer(){
    if (timerInterval){
        clearInterval(timerInterval);
        timerInterval = null;
    }
}

function resetTimer(){
    runStartedAt = null;
    stopTimer();
    document.getElementById("inlineStatusValue").textContent = "IDLE • 00:00";
}

function makePreviewSlideDataUri(title, subtitle, accent){
    const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="720" height="960" viewBox="0 0 720 960">
        <defs>
            <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#111111"/>
                <stop offset="100%" stop-color="#1b1b1b"/>
            </linearGradient>
            <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stop-color="#ff7a00"/>
                <stop offset="100%" stop-color="${accent}"/>
            </linearGradient>
        </defs>
        <rect width="720" height="960" fill="url(#bg)"/>
        <rect x="50" y="52" width="620" height="6" rx="3" fill="url(#accent)"/>
        <rect x="50" y="120" width="620" height="310" rx="20" fill="#0f0f0f" stroke="rgba(255,255,255,0.12)"/>
        <circle cx="360" cy="275" r="92" fill="rgba(255,122,0,0.12)"/>
        <rect x="120" y="228" width="480" height="94" rx="16" fill="rgba(255,255,255,0.03)"/>
        <text x="60" y="520" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="700" fill="#ffffff">${title}</text>
        <text x="60" y="575" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="#cfcfcf">${subtitle}</text>
        <rect x="60" y="650" width="600" height="16" rx="8" fill="rgba(255,255,255,0.10)"/>
        <rect x="60" y="688" width="560" height="16" rx="8" fill="rgba(255,255,255,0.08)"/>
        <rect x="60" y="726" width="585" height="16" rx="8" fill="rgba(255,255,255,0.08)"/>
        <rect x="60" y="764" width="520" height="16" rx="8" fill="rgba(255,255,255,0.08)"/>
        <text x="60" y="890" font-family="Arial, Helvetica, sans-serif" font-size="18" fill="#8f8f8f">Preview mockup for Beta v1.6 flow</text>
    </svg>`;
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

function makeAccentForIndex(index){
    const accents = ["#ffb347", "#ff9955", "#ffc266", "#ff9c3d", "#ffcf70"];
    return accents[index % accents.length];
}


function projectFileUrl(path){
    if (!path) return "";
    const rel = String(path).replace(BASE_PATH_PREFIX, "").replace(/^\/+/, "");
    return "/project-file?path=" + encodeURIComponent(rel);
}

function normalizeImageOption(option, fallbackSlide, optionIndex){
    const normalized = option || {};
    const imagePath = normalized.image_path || "";
    return {
        rank: normalized.rank || optionIndex + 1,
        option_id: normalized.option_id || `option_${optionIndex + 1}`,
        label: normalized.label || `Option ${optionIndex + 1}`,
        focus: normalized.focus || "",
        image_path: imagePath,
        image_name: normalized.image_name || "",
        image_source: normalized.image_source || "",
        image_url: normalized.image_url || projectFileUrl(imagePath)
    };
}

function normalizeSlideForRefine(slide, index){
    const normalized = slide || {};
    const imagePath = normalized.image_path || "";
    const options = Array.isArray(normalized.image_options)
        ? normalized.image_options.map((option, optionIndex) => normalizeImageOption(option, normalized, optionIndex))
        : [];

    return {
        type: normalized.type || normalized.stage || normalized.layout || `Slide ${index + 1}`,
        title: normalized.title || `Slide ${index + 1}`,
        subtitle: normalized.subtitle || "",
        body: normalized.body || normalized.content || normalized.text || normalized.copy || "",
        caption: normalized.caption || "Generated slide preview.",
        accent: normalized.accent || makeAccentForIndex(index),
        layout: normalized.layout || "text",
        stage: normalized.stage || "refine",
        image_url: normalized.image_url || projectFileUrl(imagePath),
        image_name: normalized.image_name || "",
        image_path: imagePath,
        image_source: normalized.image_source || "",
        image_options: options,
        selected_option_id: normalized.selected_option_id || (options[0] && options[0].option_id) || "selected"
    };
}

function previewImageSrcForSlide(slide){
    if (slide && slide.image_url){
        return slide.image_url;
    }
    if (slide && slide.image_path){
        return projectFileUrl(slide.image_path);
    }
    return makePreviewSlideDataUri((slide && slide.title) || "", (slide && slide.subtitle) || "", (slide && slide.accent) || "#ffb347");
}

async function syncLatestSlidesForPreview(){
    const loaded = await loadLatestRefineSlides();
    if (loaded) latestSlidesLoadedForComplete = true;
    renderDeckPreview();
    if (activeCompleteView === "refine") {
        renderCurrentRefineSlide();
    }
    return loaded;
}

async function loadLatestRefineSlides(){
    try {
        const response = await fetch("/project-file?path=output/latest_deck_manifest.json", { cache: "no-store" });
        if (!response.ok) throw new Error("manifest_missing");

        const data = await response.json();
        if (!Array.isArray(data) || !data.length) throw new Error("manifest_empty");

        refineSlides = data.map((slide, index) => normalizeSlideForRefine(slide, index));
        latestRefineProjectTitle = refineSlides[0]?.title || "UNTITLED PROJECT";
        currentRefineSlide = Math.min(currentRefineSlide, Math.max(refineSlides.length - 1, 0));
        return true;
    } catch (err) {
        refineSlides = fallbackSlides.map((slide, index) => normalizeSlideForRefine(slide, index));
        latestRefineProjectTitle = "UNTITLED PROJECT";
        currentRefineSlide = Math.min(currentRefineSlide, Math.max(refineSlides.length - 1, 0));
        return false;
    }
}

function renderDeckPreview(){
    const strip = document.getElementById("deckPreviewStrip");
    if (!strip) return;

    if (!Array.isArray(refineSlides) || !refineSlides.length){
        strip.innerHTML = "";
        return;
    }

    strip.innerHTML = refineSlides.map((slide, index) => `
        <div class="deck-preview-card">
            <img src="${previewImageSrcForSlide(slide)}" alt="Preview slide ${index + 1}">
            <div class="deck-preview-card-title">Slide ${index + 1} • ${slide.type}</div>
        </div>
    `).join("");
}

function renderRefineSlideList(){
    const list = document.getElementById("slideList");
    if (!list) return;
    list.innerHTML = refineSlides.map((slide, index) => {
        const active = index === currentRefineSlide ? "active" : "";
        return `<div class="slide-pill ${active}">${index + 1}. ${slide.type}</div>`;
    }).join("");
}


function renderImageOptionStrip(){
    const strip = document.getElementById("imageOptionStrip");
    const empty = document.getElementById("imageOptionEmpty");
    if (!strip || !empty || !Array.isArray(refineSlides) || !refineSlides.length) return;

    const slide = refineSlides[currentRefineSlide];
    const options = Array.isArray(slide.image_options) ? slide.image_options : [];

    if (!options.length){
        strip.innerHTML = "";
        empty.style.display = "block";
        return;
    }

    empty.style.display = "none";
    const noImageActive = slide.image_path === "__none__" ? "active" : "";
    strip.innerHTML = options.map((option, optionIndex) => {
        const active = option.option_id === slide.selected_option_id ? "active" : "";
        return `
            <div class="image-option-thumb ${active}" onclick="openImageOptionModal(${optionIndex})">
                <img src="${option.image_url || previewImageSrcForSlide(slide)}" alt="${option.label || 'Image option'}">
                <div class="image-option-thumb-label">${option.label || `Option ${optionIndex + 1}`}</div>
            </div>
        `;
    }).join("") + `
        <div class="image-option-thumb no-image-tile ${noImageActive}" onclick="selectNoImage()" title="Text only — no background image">
            <div class="no-image-icon">T</div>
            <div class="image-option-thumb-label">No Image</div>
        </div>
    `;
}

function openImageOptionModal(optionIndex){
    const slide = refineSlides[currentRefineSlide];
    const options = Array.isArray(slide.image_options) ? slide.image_options : [];
    if (!options.length) return;
    currentImageOptionModalIndex = Math.max(0, Math.min(optionIndex, options.length - 1));
    renderImageOptionModal();
    document.getElementById("imageOptionModal").classList.add("show");
}

function renderImageOptionModal(){
    const slide = refineSlides[currentRefineSlide];
    const options = Array.isArray(slide.image_options) ? slide.image_options : [];
    const option = options[currentImageOptionModalIndex];
    if (!option) return;

    document.getElementById("imageOptionModalTitle").textContent = option.label || "Preview Image Option";
    document.getElementById("imageOptionModalPreview").src = option.image_url || previewImageSrcForSlide(slide);
    document.getElementById("imageOptionModalMeta").textContent =
        `Slide ${currentRefineSlide + 1} • ${slide.title || slide.type || "Slide"} • ${option.focus || "image option"}`;
}

function shiftImageOptionModal(direction){
    const slide = refineSlides[currentRefineSlide];
    const options = Array.isArray(slide.image_options) ? slide.image_options : [];
    if (!options.length) return;
    currentImageOptionModalIndex = (currentImageOptionModalIndex + direction + options.length) % options.length;
    renderImageOptionModal();
}

function selectCurrentImageOption(){
    const slide = refineSlides[currentRefineSlide];
    const options = Array.isArray(slide.image_options) ? slide.image_options : [];
    const option = options[currentImageOptionModalIndex];
    if (!option) return;

    slide.selected_option_id = option.option_id || "selected";
    slide.image_path = option.image_path || "";
    slide.image_name = option.image_name || "";
    slide.image_source = option.image_source || "";
    slide.image_url = option.image_url || "";
    document.getElementById("refineSlideImage").src = previewImageSrcForSlide(slide);
    document.getElementById("refineSlideCaption").textContent = `${option.label || "Current Pick"} • ${slide.image_name || slide.title || "image selected"}`;
    renderImageOptionStrip();
    renderDeckPreview();
    closeModal("imageOptionModal");
}

async function loadSlideImageOptions(){
    const slide = refineSlides[currentRefineSlide];
    const title = document.getElementById("refineTitleInput").value || slide.title || "";
    const body = document.getElementById("refineBodyInput").value || slide.body || "";
    const userPrompt = (document.getElementById("refineImagePrompt").value || "").trim();
    const btn = document.getElementById("loadOptionsBtn");

    btn.disabled = true;
    btn.textContent = "Generating options…";

    try {
        const resp = await fetch("/generate-slide-options", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                slide_title: title,
                slide_body: body,
                user_prompt: userPrompt,
                slide_number: currentRefineSlide + 1,
                current_image_path: slide.image_path || "",
                current_image_url: slide.image_url || "",
            })
        });
        const data = await resp.json();
        if (data.options && data.options.length) {
            slide.image_options = [
                ...(slide.image_options || []).filter(o => o.option_id === "selected"),
                ...data.options
            ];
            renderImageOptionStrip();
            showInfoModal("Image Options", `${data.options.length} new options loaded. Browse them in the image strip below.`);
        } else {
            showInfoModal("Image Options", data.error || "Could not generate options. Try again.");
        }
    } catch(e) {
        showInfoModal("Image Options", "Something went wrong. Try again.");
    } finally {
        btn.disabled = false;
        btn.textContent = "Load Image Options";
    }
}

async function regenerateSlideImage(){
    const slide = refineSlides[currentRefineSlide];
    const title = document.getElementById("refineTitleInput").value || slide.title || "";
    const body = document.getElementById("refineBodyInput").value || slide.body || "";
    const userPrompt = (document.getElementById("refineImagePrompt").value || "").trim();
    const btn = document.getElementById("regenImageBtn");

    btn.disabled = true;
    btn.textContent = "Generating…";

    try {
        const resp = await fetch("/regenerate-slide-image", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                slide_title: title,
                slide_body: body,
                user_prompt: userPrompt,
                slide_number: currentRefineSlide + 1,
            })
        });
        const data = await resp.json();
        if (data.image_url) {
            slide.image_url = data.image_url;
            slide.image_path = data.image_path || "";
            slide.image_source = "fal_generated";
            slide.selected_option_id = "regen";
            document.getElementById("refineSlideImage").src = data.image_url;
            document.getElementById("refineSlideCaption").textContent = "Regenerated image";
            renderImageOptionStrip();
            renderDeckPreview();
        } else {
            showInfoModal("Image Generation", data.error || "Generation failed. Try again.");
        }
    } catch(e) {
        showInfoModal("Image Generation", "Something went wrong. Try again.");
    } finally {
        btn.disabled = false;
        btn.textContent = "Regenerate Image";
    }
}

function selectNoImage(){
    const slide = refineSlides[currentRefineSlide];
    slide.selected_option_id = "__none__";
    slide.image_path = "__none__";
    slide.image_name = "none";
    slide.image_source = "text_only";
    slide.image_url = "";
    document.getElementById("refineSlideImage").src = "";
    document.getElementById("refineSlideCaption").textContent = "Text Only — no background image";
    renderImageOptionStrip();
    renderDeckPreview();
}

function renderCurrentRefineSlide(){
    if (!Array.isArray(refineSlides) || !refineSlides.length){
        return;
    }

    const slide = refineSlides[currentRefineSlide];
    document.getElementById("slideCounter").textContent = `Slide ${currentRefineSlide + 1} of ${refineSlides.length}`;
    document.getElementById("slideType").textContent = slide.type;
    document.getElementById("refineTitleInput").value = slide.title;
    document.getElementById("refineSubtitleInput").value = slide.subtitle;
    document.getElementById("refineBodyInput").value = slide.body;
    document.getElementById("refineSlideImage").src = previewImageSrcForSlide(slide);
    document.getElementById("refineSlideCaption").textContent = slide.caption || `Preview for ${latestRefineProjectTitle}`;
    renderImageOptionStrip();
    document.getElementById("refineBackBtn").disabled = currentRefineSlide === 0;
    document.getElementById("refineNextBtn").disabled = currentRefineSlide === refineSlides.length - 1;
    renderRefineSlideList();
}

function saveCurrentRefineSlide(){
    if (!Array.isArray(refineSlides) || !refineSlides.length){
        return;
    }
    const slide = refineSlides[currentRefineSlide];
    slide.title = document.getElementById("refineTitleInput").value;
    slide.subtitle = document.getElementById("refineSubtitleInput").value;
    slide.body = document.getElementById("refineBodyInput").value;
    renderCurrentRefineSlide();
    renderDeckPreview();
}

async function openRefinementStage(){
    activeCompleteView = "refine";
    const loaded = await loadLatestRefineSlides();
    if (loaded) latestSlidesLoadedForComplete = true;
    document.getElementById("previewStage").style.display = "none";
    document.getElementById("refinementStage").style.display = "block";
    renderDeckPreview();
    renderCurrentRefineSlide();
}

function returnToPreviewStage(){
    saveCurrentRefineSlide();
    activeCompleteView = "preview";
    document.getElementById("refinementStage").style.display = "none";
    document.getElementById("previewStage").style.display = "block";
    renderDeckPreview();
}

function goPrevRefineSlide(){
    saveCurrentRefineSlide();
    if (currentRefineSlide > 0){
        currentRefineSlide -= 1;
        renderCurrentRefineSlide();
    }
}

function goNextRefineSlide(){
    saveCurrentRefineSlide();
    if (currentRefineSlide < refineSlides.length - 1){
        currentRefineSlide += 1;
        renderCurrentRefineSlide();
    }
}

function changePlaceholderImage(){
    showInfoModal("Change Image", "Image selection is the next pass. For now, refine text first.");
}
function openBuildProgressModal(){
    const modal = document.getElementById("buildProgressModal");
    document.getElementById("buildProgressTitle").textContent = "Building Your Deck";
    document.getElementById("buildProgressCopy").textContent = "This takes about 30–60 seconds while we generate your images.";
    document.getElementById("buildProgressStage").textContent = "Analyzing script\u2026";
    document.getElementById("buildProgressFill").style.width = "10%";
    document.getElementById("buildProgressWorking").style.display = "block";
    document.getElementById("buildProgressActions").style.display = "none";
    modal.classList.add("show");
}

function updateBuildProgressModal(status){
    const modal = document.getElementById("buildProgressModal");
    if (!modal.classList.contains("show")) return;
    const fill = document.getElementById("buildProgressFill");
    const stage = document.getElementById("buildProgressStage");
    if (status === "ANALYZING"){
        stage.textContent = "Analyzing script with Developum AI Engine\u2026";
        fill.style.width = "35%";
    } else if (status === "BUILDING"){
        stage.textContent = "Generating images and building deck\u2026";
        fill.style.width = "75%";
    } else if (status === "COMPLETE"){
        fill.style.width = "100%";
        document.getElementById("buildProgressWorking").style.display = "none";
        document.getElementById("buildProgressTitle").textContent = "Deck Ready";
        document.getElementById("buildProgressCopy").textContent = "Your pitch deck has been generated.";
        document.getElementById("buildProgressActions").style.display = "flex";
    } else if (status === "ERROR"){
        document.getElementById("buildProgressWorking").style.display = "none";
        document.getElementById("buildProgressTitle").textContent = "Build Failed";
        document.getElementById("buildProgressCopy").textContent = "Something went wrong. Please try again.";
        document.getElementById("buildProgressActions").style.display = "flex";
        document.getElementById("buildProgressActions").querySelector("button").textContent = "Close";
    }
}

function closeBuildProgressModal(){
    document.getElementById("buildProgressModal").classList.remove("show");
}

    function openRegenerateDeckModal(){
    const modal = document.getElementById("regenDeckModal");
    const title = document.getElementById("regenDeckModalTitle");
    const copy = document.getElementById("regenDeckModalCopy");
    const working = document.getElementById("regenDeckWorkingState");
    const actions = document.getElementById("regenDeckModalActions");

    title.textContent = "Regenerating Deck";
    copy.textContent = "Please wait while your updated deck is rebuilt.";
    working.style.display = "block";
    actions.style.display = "none";
    modal.classList.add("show");
}

function setRegenerateDeckModalSuccess(){
    const title = document.getElementById("regenDeckModalTitle");
    const copy = document.getElementById("regenDeckModalCopy");
    const working = document.getElementById("regenDeckWorkingState");
    const actions = document.getElementById("regenDeckModalActions");

    title.textContent = "Deck Complete";
    copy.textContent = "Your refined deck has been rebuilt successfully.";
    working.style.display = "none";
    actions.style.display = "flex";
}

function setRegenerateDeckModalError(message){
    const title = document.getElementById("regenDeckModalTitle");
    const copy = document.getElementById("regenDeckModalCopy");
    const working = document.getElementById("regenDeckWorkingState");
    const actions = document.getElementById("regenDeckModalActions");

    title.textContent = "Regenerate Deck";
    copy.textContent = message || "Something went wrong while regenerating the deck.";
    working.style.display = "none";
    actions.style.display = "flex";
}

function finishRegenerateDeckFlow(){
    closeModal("regenDeckModal");
    activeCompleteView = "preview";
    document.getElementById("refinementStage").style.display = "none";
    document.getElementById("previewStage").style.display = "block";
    renderDeckPreview();
}

async function regenerateDeckPlaceholder(){
    saveCurrentRefineSlide();
    openRegenerateDeckModal();

    try {
        const response = await fetch("/refine-deck", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: latestRefineProjectTitle, slides: refineSlides })
        });

        const data = await response.json();

        if (!response.ok){
            setRegenerateDeckModalError(data.error || "Deck regeneration failed.");
            return;
        }

        await syncLatestSlidesForPreview();
        latestSlidesLoadedForComplete = true;
        setRegenerateDeckModalSuccess();
    } catch (err) {
        setRegenerateDeckModalError("Connection issue during regeneration.");
    }
}


// ===== JAVASCRIPT: ACTOR PREP FLOW START ==============
function startActorPrepFlow(){
    resetCreateProject();
    document.getElementById("actorPrepModal").classList.add("show");
}

async function submitActorPrep(){
    const role = (document.getElementById("actorRoleInput").value || "").trim();
    const fileInput = document.getElementById("actorPrepFile");
    const file = fileInput && fileInput.files && fileInput.files.length ? fileInput.files[0] : null;

    if (!role){
        showInfoModal("Actor Preparation", "Please enter the role you are preparing.");
        return;
    }

    if (!file){
        showInfoModal("Actor Preparation", "Please choose a script before continuing.");
        return;
    }

    const btn = document.querySelector("#actorPrepModal .primary-button[onclick='submitActorPrep()']");
    if (btn){ btn.disabled = true; btn.textContent = "Analyzing..."; btn.classList.add("analyzing"); }

    const formData = new FormData();
    formData.append("character_name", role);
    formData.append("script", file);

    try {
        const response = await fetch("/actor-prep-pass", {
            method: "POST",
            body: formData
        });
        const data = await response.json();

        if (response.status === 422 && data.needs_paste){
            if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
            closeModal("actorPrepModal");
            document.getElementById("actorPrepPasteModal").classList.add("show");
            return;
        }

        if (!response.ok){
            if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
            showInfoModal("Actor Preparation", data.error || "Actor preparation failed.");
            return;
        }

        document.getElementById("actorPrepSummaryCopy").textContent = data.summary_note || "Your actor preparation packet is ready.";
        if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
        closeModal("actorPrepModal");
        document.getElementById("actorPrepCompleteModal").classList.add("show");
    } catch (err) {
        if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
        showInfoModal("Actor Preparation", "Actor preparation failed. Please try again.");
    }
}

async function submitActorPrepPaste(){
    const role = (document.getElementById("actorRoleInput").value || "").trim();
    const pastedText = (document.getElementById("actorPrepPasteText").value || "").trim();

    if (!role){
        showInfoModal("Actor Preparation", "Please enter the role you are preparing.");
        return;
    }

    if (!pastedText){
        showInfoModal("Actor Preparation", "Please paste the script text to continue.");
        return;
    }

    const formData = new FormData();
    formData.append("character_name", role);
    formData.append("script_text", pastedText);

    try {
        const response = await fetch("/actor-prep-pass", {
            method: "POST",
            body: formData
        });
        const data = await response.json();

        if (!response.ok){
            showInfoModal("Actor Preparation", data.error || "Actor preparation failed.");
            return;
        }

        document.getElementById("actorPrepSummaryCopy").textContent = data.summary_note || "Your actor preparation packet is ready.";
        closeModal("actorPrepPasteModal");
        document.getElementById("actorPrepCompleteModal").classList.add("show");
    } catch (err) {
        showInfoModal("Actor Preparation", "Actor preparation failed. Please try again.");
    }
}
// ===== JAVASCRIPT: ACTOR PREP FLOW END ================


// ===== JAVASCRIPT: ACTOR BOOKED FLOW START ==============
function startActorBookedFlow(){
    resetCreateProject();
    document.getElementById("actorBookedModal").classList.add("show");
}

async function submitActorBooked(){
    const role = (document.getElementById("actorBookedRoleInput").value || "").trim();
    const fileInput = document.getElementById("actorBookedFile");
    const file = fileInput && fileInput.files && fileInput.files.length ? fileInput.files[0] : null;

    if (!role){
        showInfoModal("Booked Role Analyzer", "Please enter the role you booked.");
        return;
    }

    if (!file){
        showInfoModal("Booked Role Analyzer", "Please choose a script before continuing.");
        return;
    }

    const btn = document.querySelector("#actorBookedModal .primary-button[onclick='submitActorBooked()']");
    if (btn){ btn.disabled = true; btn.textContent = "Analyzing..."; btn.classList.add("analyzing"); }

    const formData = new FormData();
    formData.append("character_name", role);
    formData.append("script", file);

    try {
        const response = await fetch("/actor-booked-pass", {
            method: "POST",
            body: formData
        });
        const data = await response.json();

        if (response.status === 422 && data.needs_paste){
            if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
            closeModal("actorBookedModal");
            document.getElementById("actorBookedPasteModal").classList.add("show");
            return;
        }

        if (!response.ok){
            if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
            showInfoModal("Booked Role Analyzer", data.error || "Booked role analysis failed.");
            return;
        }

        document.getElementById("actorBookedSummaryCopy").textContent = data.summary_note || "Your booked role preparation packet is ready.";
        if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
        closeModal("actorBookedModal");
        document.getElementById("actorBookedCompleteModal").classList.add("show");
    } catch (err) {
        if (btn){ btn.disabled = false; btn.textContent = "Analyze"; btn.classList.remove("analyzing"); }
        showInfoModal("Booked Role Analyzer", "Booked role analysis failed. Please try again.");
    }
}

async function submitActorBookedPaste(){
    const role = (document.getElementById("actorBookedRoleInput").value || "").trim();
    const pastedText = (document.getElementById("actorBookedPasteText").value || "").trim();

    if (!role){
        showInfoModal("Booked Role Analyzer", "Please enter the role you booked.");
        return;
    }

    if (!pastedText){
        showInfoModal("Booked Role Analyzer", "Please paste the script text to continue.");
        return;
    }

    const formData = new FormData();
    formData.append("character_name", role);
    formData.append("script_text", pastedText);

    try {
        const response = await fetch("/actor-booked-pass", {
            method: "POST",
            body: formData
        });
        const data = await response.json();

        if (!response.ok){
            showInfoModal("Booked Role Analyzer", data.error || "Booked role analysis failed.");
            return;
        }

        document.getElementById("actorBookedSummaryCopy").textContent = data.summary_note || "Your booked role preparation packet is ready.";
        closeModal("actorBookedPasteModal");
        document.getElementById("actorBookedCompleteModal").classList.add("show");
    } catch (err) {
        showInfoModal("Booked Role Analyzer", "Booked role analysis failed. Please try again.");
    }
}
// ===== JAVASCRIPT: ACTOR BOOKED FLOW END ================


function updateStatusUI(status){
    const inlineStatusEl = document.getElementById("inlineStatusValue");
    const inlineStageEl = document.getElementById("inlineStageValue");
    const previousStatus = lastStatus;

    lastStatus = status;

    const progress = document.getElementById("progressFill");
    if (status === "UPLOADED") progress.style.width = "20%";
    if (status === "ANALYZING" || status === "running") progress.style.width = "50%";
    if (status === "BUILDING") progress.style.width = "85%";
    if (status === "COMPLETE") progress.style.width = "100%";

    const activeStatuses = ["UPLOADED", "ANALYZING", "BUILDING", "DEMO_RUNNING"];
    if (activeStatuses.includes(status)) startTimer();

    if (status === "IDLE"){
        resetTimer();
        inlineStageEl.textContent = "Awaiting input...";
        document.body.classList.remove("complete-mode");
    } else if (status === "UPLOADED"){
        inlineStatusEl.textContent = "UPLOADED • 00:00";
        inlineStageEl.textContent = "Preparing engine";
    } else if (status === "ANALYZING" || status === "running"){
        inlineStageEl.textContent = "Analyzing script";
        updateBuildProgressModal("ANALYZING");
    } else if (status === "BUILDING"){
        inlineStageEl.textContent = "Finalizing deck...";
        updateBuildProgressModal("BUILDING");
    } else if (status === "DEMO_RUNNING"){
        inlineStageEl.textContent = "Preparing engine";
    } else if (status === "COMPLETE"){
        updateBuildProgressModal("COMPLETE");
        stopTimer();
        stopQuoteRotation();
        buildInFlight = false;
        document.body.classList.add("complete-mode");
        document.getElementById("buildProgressBar").style.display = "none";
        document.getElementById("liveProcessLog").style.display = "none";
        document.getElementById("buildCopy").style.display = "none";
        document.getElementById("buildMeta").style.display = "none";
        document.getElementById("completePanel").style.display = "block";

        if (activeCompleteView === "refine") {
            document.getElementById("previewStage").style.display = "none";
            document.getElementById("refinementStage").style.display = "block";
            if (previousStatus !== "COMPLETE" || !latestSlidesLoadedForComplete) {
                syncLatestSlidesForPreview().then(() => {
                    renderCurrentRefineSlide();
                });
            }
        } else {
            document.getElementById("previewStage").style.display = "block";
            document.getElementById("refinementStage").style.display = "none";
            if (previousStatus !== "COMPLETE" || !latestSlidesLoadedForComplete) {
                syncLatestSlidesForPreview();
            }
        }
    } else if (status === "ERROR"){
        updateBuildProgressModal("ERROR");
        stopTimer();
        buildInFlight = false;
        inlineStageEl.textContent = "Check terminal / backend";
        document.body.classList.remove("complete-mode");
        document.getElementById("liveProcessLog").style.display = "block";
        document.getElementById("buildCopy").style.display = "block";
        document.getElementById("buildMeta").style.display = "flex";
        document.getElementById("completePanel").style.display = "none";
    } else {
        inlineStageEl.textContent = "Processing";
        document.body.classList.remove("complete-mode");
    }
    updateProgressForStatus(status);
    renderLiveProcessLog(status);
}

async function pollStatus(){
    try {
        const response = await fetch("/status", { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();

        if (data && data.status) {
            if (buildInFlight && !sawFreshBuildStatus) {
                if (data.status === "ANALYZING" || data.status === "BUILDING" || data.status === "running") {
                    sawFreshBuildStatus = true;
                } else {
                    return;
                }
            }
            updateStatusUI(data.status);
        }
    } catch (e) {}
}

refineSlides = fallbackSlides.map((slide, index) => normalizeSlideForRefine(slide, index));
renderDeckPreview();
renderCurrentRefineSlide();
updateStatusUI("IDLE");
setInterval(pollStatus, 1200);
pollStatus();
