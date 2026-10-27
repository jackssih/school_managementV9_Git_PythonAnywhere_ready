/* ACE module — table filtering, bulk-enroll helpers, and the report-card
   preview + PDF download. The preview/download mirrors the Primary report
   module (same overlay, Individual / All-in-One tabs, student list, A4 PDF)
   so both behave identically. */
(function () {
    "use strict";

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    /* ---------- Edit an ACE grade's supervisor ---------- */
    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-ace-edit-grade]");
        if (!button) return;
        const form = document.getElementById("aceEditGradeForm");
        if (!form) return;
        form.action = form.dataset.actionTemplate.replace(/\/0\/supervisor$/, `/${button.dataset.classId}/supervisor`);
        document.getElementById("ace-edit-supervisor").value = button.dataset.supervisorId || "";
        document.getElementById("aceEditGradeHeading").textContent = `Edit ACE Grade ${button.dataset.grade}`;
        openModal("aceEditGradeModal");
    });

    /* ---------- Simple table filter (the search boxes) ---------- */
    document.addEventListener("input", (event) => {
        const input = event.target.closest("[data-ace-filter]");
        if (!input) return;
        const query = input.value.trim().toLowerCase();
        document.querySelectorAll(`${input.dataset.aceFilter} tbody tr`).forEach((row) => {
            if (row.classList.contains("ace-empty-row")) return;
            row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
        });
    });

    /* ---------- Bulk enrol modal ---------- */
    function initBulkEnroll() {
        const list = document.getElementById("aceBulkList");
        if (!list) return;
        const search = document.getElementById("aceBulkSearch");
        const count = document.getElementById("aceBulkCount");
        const selectAll = document.getElementById("aceBulkSelectAll");
        const rows = () => Array.from(list.querySelectorAll(".bulk-student-row"));
        const refresh = () => {
            const n = list.querySelectorAll("input:checked").length;
            count.textContent = `${n} student${n === 1 ? "" : "s"} selected`;
        };
        search.addEventListener("input", () => {
            const q = search.value.trim().toLowerCase();
            rows().forEach((row) => { row.hidden = Boolean(q) && !row.dataset.name.includes(q); });
        });
        list.addEventListener("change", refresh);
        selectAll.addEventListener("click", () => {
            const visible = rows().filter((row) => !row.hidden).map((row) => row.querySelector("input"));
            const allOn = visible.length > 0 && visible.every((box) => box.checked);
            visible.forEach((box) => { box.checked = !allOn; });
            selectAll.textContent = allOn ? "Select all" : "Clear all";
            refresh();
        });
        // closeModal() resets the form; keep the counter honest afterwards.
        new MutationObserver(refresh).observe(document.getElementById("aceBulkEnrollModal"), { attributes: true, attributeFilter: ["class"] });
    }

    /* ---------- Report preview ---------- */
    const overlay = document.getElementById("acePreviewOverlay");
    const source = document.getElementById("aceReportSource");
    let activeStudentId = null;
    let previewMode = "individual";

    const pages = () => (source ? Array.from(source.querySelectorAll(".ace-report-page")) : []);
    const pageFor = (id) => pages().find((page) => Number(page.dataset.studentId) === Number(id));

    function renderStudentList() {
        const list = document.getElementById("aceStudentList");
        const query = document.getElementById("aceStudentSearch").value.trim().toLowerCase();
        const generated = overlay.dataset.generated || "";
        const items = pages().filter((page) => page.dataset.studentName.toLowerCase().includes(query));
        list.innerHTML = items.length ? items.map((page) => `
            <button type="button" class="report-student-item ${Number(page.dataset.studentId) === activeStudentId ? "active" : ""}" data-student-id="${page.dataset.studentId}">
                <i class="ti ti-file-text"></i>
                <span>
                    <strong>${escapeHtml(page.dataset.studentName)}</strong>
                    <small>${escapeHtml(generated)} · Generated</small>
                </span>
            </button>`).join("") : '<p class="form-subheading">No students found.</p>';
    }

    // On phones: All-in-One only (tabs/list hidden in CSS) and every A4 page
    // scaled to fit the screen width.
    const REPORT_DESIGN_WIDTH = 820;
    const mobileQuery = window.matchMedia("(max-width: 760px)");
    const isMobileView = () => mobileQuery.matches;

    function fitReportPages() {
        const doc = document.getElementById("aceDocument");
        const area = doc && doc.closest(".report-document-area");
        if (!doc || !area) return;
        if (!isMobileView()) { doc.style.removeProperty("--report-fit-scale"); return; }
        const scale = Math.max(0.2, Math.min(1, (area.clientWidth - 16) / REPORT_DESIGN_WIDTH));
        doc.style.setProperty("--report-fit-scale", scale.toFixed(4));
    }

    function renderPreview() {
        const doc = document.getElementById("aceDocument");
        const all = pages();
        const chosen = (previewMode === "all" || isMobileView()) ? all : [pageFor(activeStudentId) || all[0]].filter(Boolean);
        doc.innerHTML = "";
        chosen.forEach((page) => doc.appendChild(page.cloneNode(true)));
        document.getElementById("acePageCount").textContent = `${chosen.length} ${chosen.length === 1 ? "Page" : "Pages"}`;
        renderStudentList();
        fitReportPages();
    }

    function setMode(mode) {
        previewMode = mode;
        overlay.querySelectorAll(".report-preview-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.previewMode === mode));
    }

    function openPreview(studentId) {
        const all = pages();
        if (!overlay || !all.length) return;
        activeStudentId = Number(studentId) || Number(all[0].dataset.studentId);
        document.getElementById("aceStudentSearch").value = "";
        setMode("individual");
        overlay.classList.add("open");
        renderPreview();
    }

    function closePreview() { overlay.classList.remove("open"); }

    /* ---------- PDF download (same approach as the Primary reports) ---------- */
    const A4_WIDTH = 595.28;
    const A4_HEIGHT = 841.89;

    function slug(text) {
        return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    }

    function waitForImages(root) {
        return Promise.all(Array.from(root.querySelectorAll("img")).map((img) => {
            if (img.complete && img.naturalWidth > 0) return Promise.resolve();
            return new Promise((resolve) => {
                img.addEventListener("load", resolve, { once: true });
                img.addEventListener("error", resolve, { once: true });
            });
        }));
    }

    async function downloadPdf(pageNodes, filenameBase, button) {
        if (button && button.disabled) return;

        // Safari blocks window.open() once an async render has finished, so
        // open the tab synchronously inside the click (same as Primary).
        const ua = navigator.userAgent;
        const isIOS = /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
        const isSafari = isIOS || (/Safari/i.test(ua) && !/Chrome|CriOS|FxiOS|Edg|Android/i.test(ua));
        const pdfWindow = isSafari ? window.open("about:blank", "_blank") : null;
        const abort = (message) => {
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert(message);
        };

        if (!pageNodes.length) return abort("There is no report content to download.");
        if (typeof html2canvas !== "function") return abort("The PDF renderer is not loaded. Please refresh the page and try again.");
        if (!window.jspdf || !window.jspdf.jsPDF) return abort("The PDF library is not loaded. Please refresh the page and try again.");

        const originalIcon = button ? button.innerHTML : "";
        if (button) { button.disabled = true; button.innerHTML = '<i class="ti ti-loader-2"></i>'; }

        // Render clean clones in a top-level container, away from the fixed
        // preview overlay and its scrolling area, so nothing clips the capture.
        const holder = document.createElement("div");
        holder.id = "acePrintContainer";
        pageNodes.forEach((node) => holder.appendChild(node.cloneNode(true)));
        document.body.appendChild(holder);

        try {
            const { jsPDF } = window.jspdf;
            const pdf = new jsPDF({ unit: "pt", format: "a4", orientation: "portrait", compress: true });

            await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            if (document.fonts) {
                try { await document.fonts.load('700 17px "Lobster Two"'); } catch (e) { /* fall back to cursive */ }
                await document.fonts.ready;
            }
            await waitForImages(holder);

            const nodes = Array.from(holder.querySelectorAll(".ace-report-page"));
            for (let index = 0; index < nodes.length; index += 1) {
                const canvas = await html2canvas(nodes[index], {
                    scale: 2, useCORS: true, allowTaint: false, backgroundColor: "#ffffff",
                    logging: false, scrollX: 0, scrollY: -window.scrollY,
                    windowWidth: Math.max(document.documentElement.clientWidth, 900),
                    // The live capture copy sits off screen; bring it back
                    // to the origin only inside html2canvas's own clone.
                    onclone: (clonedDocument) => {
                        const clonedHolder = clonedDocument.getElementById("acePrintContainer");
                        if (clonedHolder) {
                            clonedHolder.style.left = "0px";
                            clonedHolder.style.top = "0px";
                            clonedHolder.style.zIndex = "300";
                        }
                    },
                });
                if (!canvas.width || !canvas.height) throw new Error(`Report page ${index + 1} produced an empty image.`);

                const ratio = Math.min(A4_WIDTH / canvas.width, A4_HEIGHT / canvas.height);
                const w = canvas.width * ratio;
                const h = canvas.height * ratio;
                if (index > 0) pdf.addPage("a4", "portrait");
                pdf.setFillColor(255, 255, 255);
                pdf.rect(0, 0, A4_WIDTH, A4_HEIGHT, "F");
                pdf.addImage(canvas.toDataURL("image/jpeg", 0.98), "JPEG", (A4_WIDTH - w) / 2, (A4_HEIGHT - h) / 2, w, h, undefined, "FAST");
            }

            const url = URL.createObjectURL(pdf.output("blob"));
            if (pdfWindow && !pdfWindow.closed) {
                pdfWindow.location.href = url;
            } else if (isSafari) {
                window.location.href = url;
            } else {
                const link = document.createElement("a");
                link.href = url;
                link.download = `${filenameBase || "ace-report"}.pdf`;
                document.body.appendChild(link);
                link.click();
                link.remove();
            }
            window.setTimeout(() => URL.revokeObjectURL(url), 120000);
        } catch (error) {
            console.error("Could not generate ACE report PDF:", error);
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert("Something went wrong generating the PDF. Please try again.");
        } finally {
            holder.remove();
            if (button) { button.disabled = false; button.innerHTML = originalIcon; }
        }
    }

    function gradeBase() { return `ace-grade-${overlay ? overlay.dataset.grade : ""}`; }
    function reportSlug() { return (overlay && overlay.dataset.reportSlug) || "end-of-term"; }

    /* ---------- Wiring ---------- */
    document.addEventListener("click", (event) => {
        const previewBtn = event.target.closest("[data-ace-preview]");
        if (previewBtn) { openPreview(previewBtn.dataset.studentId); return; }

        const downloadAll = event.target.closest("[data-ace-download-all]");
        if (downloadAll) { downloadPdf(pages(), `${gradeBase()}-${reportSlug()}`, downloadAll); return; }

        const studentBtn = event.target.closest(".report-student-item");
        if (studentBtn && overlay && overlay.contains(studentBtn)) {
            activeStudentId = Number(studentBtn.dataset.studentId);
            setMode("individual");
            renderPreview();
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        initBulkEnroll();
        if (!overlay) return;

        document.getElementById("acePreviewClose").addEventListener("click", closePreview);
        document.addEventListener("keydown", (event) => { if (event.key === "Escape") closePreview(); });
        document.getElementById("aceStudentSearch").addEventListener("input", renderStudentList);
        overlay.querySelectorAll(".report-preview-tab").forEach((tab) => {
            tab.addEventListener("click", () => { setMode(tab.dataset.previewMode); renderPreview(); });
        });
        document.getElementById("aceDownloadBtn").addEventListener("click", (event) => {
            const button = event.currentTarget;
            if (previewMode === "all" || isMobileView()) {
                downloadPdf(pages(), `${gradeBase()}-${reportSlug()}`, button);
            } else {
                const page = pageFor(activeStudentId);
                downloadPdf(page ? [page] : [], `${gradeBase()}-${slug(page && page.dataset.studentName)}`, button);
            }
        });

        let lastMobile = isMobileView();
        window.addEventListener("resize", () => {
            if (!overlay.classList.contains("open")) return;
            if (isMobileView() !== lastMobile) { lastMobile = isMobileView(); renderPreview(); }
            else fitReportPages();
        });

        // "Save and view report" lands here with ?student_id=… — open that card.
        const auto = overlay.dataset.autoStudent;
        if (auto && pageFor(auto)) openPreview(auto);
    });
})();