(function () {
    const SHEET_LABELS = {
        bot: "B.O.T.",
        mid: "MID",
        internal: "END INT",
        external: "END EXT",
    };

    function esc(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function sheetTitle(data) {
        const yearMatch = String(data.term || "").match(/\d{4}/);
        const year = yearMatch ? yearMatch[0] : String(new Date().getFullYear());
        return `${data.class_name} ${SHEET_LABELS[data.sheet_type] || ""} TERM RESULT SHEET ${year}`.trim();
    }

    function renderPage(data, students, includeSummary) {
        const subjects = data.subjects || [];
        const subjectHeaders = subjects.map(s => `<th colspan="2">${esc(s.code)}</th>`).join("");
        const subHeaders = subjects.map(() => `<th>MKS</th><th>AGG</th>`).join("");

        const rows = students.map(student => {
            const cells = subjects.map(subject => {
                const cell = (student.cells || []).find(c => c.subject === subject.name) || {};
                return `<td>${esc(cell.mark || "")}</td><td>${esc(cell.aggregate || "")}</td>`;
            }).join("");

            return `
                <tr>
                    <td class="ms-sn">${student.sn}</td>
                    <td class="ms-name">${esc(student.name)}</td>
                    ${cells}
                    <td class="ms-total">${esc(student.total_mark)}</td>
                    <td class="ms-total">${esc(student.total_aggregate)}</td>
                    <td class="ms-div">${esc(student.division)}</td>
                </tr>
            `;
        }).join("");

        const summary = includeSummary ? `
            <div class="marksheet-grade-summary">
                <table>
                    <thead><tr><th>GRADE</th><th>I</th><th>II</th><th>III</th><th>IV</th><th>U</th><th>X</th></tr></thead>
                    <tbody><tr><th>NO.</th><td>${data.division_counts?.I || 0}</td><td>${data.division_counts?.II || 0}</td><td>${data.division_counts?.III || 0}</td><td>${data.division_counts?.IV || 0}</td><td>${data.division_counts?.U || 0}</td><td>${data.division_counts?.X || 0}</td></tr></tbody>
                </table>
            </div>
        ` : "";

        return `
            <section class="marksheet-page">
                <div class="marksheet-school-name">${esc(data.school_name || SCHOOL_NAME)}</div>
                <div class="marksheet-title">${esc(sheetTitle(data))}</div>
                <div class="marksheet-analysis-title">CLASS ANALYSIS</div>

                <table class="marksheet-table">
                    <thead>
                        <tr>
                            <th rowspan="2">S/N</th>
                            <th rowspan="2">NAM</th>
                            ${subjectHeaders}
                            <th colspan="2">TT. MRK</th>
                            <th rowspan="2">DIV</th>
                        </tr>
                        <tr>
                            ${subjects.map(() => "").join("")}
                            ${subHeaders}
                            <th>MKS</th><th>AGG</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
                ${summary}
            </section>
        `;
    }

    function renderMarksheets(data) {
        const container = document.getElementById("marksheetPrintContainer");
        if (!container) return [];
        const students = data.students || [];
        const pages = [];

        // The supplied example fits 21 learners plus the header on one
        // landscape page. Keep the same practical page density for larger classes.
        const pageSize = 21;
        for (let start = 0; start < students.length || start === 0; start += pageSize) {
            const chunk = students.slice(start, start + pageSize);
            pages.push(renderPage(data, chunk, start + pageSize >= students.length));
            if (students.length === 0) break;
        }
        container.innerHTML = pages.join("");
        return Array.from(container.querySelectorAll(".marksheet-page"));
    }

    async function downloadMarkSheet(sheetType, button) {
        // Ignore repeat clicks while a download is already being generated —
        // without this guard a second tap while html2canvas is still working
        // can leave the button permanently stuck on its spinner.
        if (button.disabled) return;

        const data = MARKSHEET_DATA?.[sheetType];
        if (!data) {
            alert("No mark sheet data is available for this class.");
            return;
        }
        if (typeof html2canvas !== "function" || !window.jspdf?.jsPDF) {
            alert("The PDF renderer is not loaded. Please refresh the page and try again.");
            return;
        }

        const pages = renderMarksheets(data);
        if (!pages.length) return;

        // Safari — on iPhone/iPad AND on the Mac desktop app — blocks the
        // window jsPDF's own save() tries to open once it runs after the
        // async canvas render, since by then the browser no longer treats it
        // as a direct result of the click. Open a blank tab synchronously, in
        // the same click, for every Safari build, then fill it in once ready.
        const ua = navigator.userAgent;
        const isIOS = /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
        const isSafari = isIOS || (/Safari/i.test(ua) && !/Chrome|CriOS|FxiOS|Edg|Android/i.test(ua));
        const pdfWindow = isSafari ? window.open("about:blank", "_blank") : null;

        const original = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<i class="ti ti-loader-2"></i> Preparing...';

        try {
            await new Promise(resolve => requestAnimationFrame(() =>
                requestAnimationFrame(resolve)
            ));
            if (document.fonts?.ready) await document.fonts.ready;

            const { jsPDF } = window.jspdf;
            const pdf = new jsPDF({
                unit: "pt",
                format: "a4",
                orientation: "landscape",
                compress: true,
            });

            const A4_WIDTH = 841.89;
            const A4_HEIGHT = 595.28;

            for (let i = 0; i < pages.length; i++) {
                const page = pages[i];
                const images = Array.from(page.querySelectorAll("img"));
                await Promise.all(images.map(img => {
                    if (img.complete) return Promise.resolve();
                    return new Promise(resolve => {
                        img.addEventListener("load", resolve, { once: true });
                        img.addEventListener("error", resolve, { once: true });
                    });
                }));

                const canvas = await html2canvas(page, {
                    scale: 2,
                    useCORS: true,
                    allowTaint: false,
                    backgroundColor: "#ffffff",
                    logging: false,
                    scrollX: 0,
                    scrollY: 0,
                });

                const ratio = Math.min(A4_WIDTH / canvas.width, A4_HEIGHT / canvas.height);
                const width = canvas.width * ratio;
                const height = canvas.height * ratio;
                const x = (A4_WIDTH - width) / 2;
                const y = (A4_HEIGHT - height) / 2;

                if (i > 0) pdf.addPage("a4", "landscape");
                pdf.setFillColor(255, 255, 255);
                pdf.rect(0, 0, A4_WIDTH, A4_HEIGHT, "F");
                pdf.addImage(
                    canvas.toDataURL("image/jpeg", 0.98),
                    "JPEG",
                    x, y, width, height, undefined, "FAST"
                );
            }

            const filename = `${data.class_name}-${sheetType}-marksheet`
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "-")
                .replace(/^-+|-+$/g, "");
            const pdfFilename = `${filename || "class-marksheet"}.pdf`;

            const pdfBlob = pdf.output("blob");
            const pdfUrl = URL.createObjectURL(pdfBlob);

            if (pdfWindow && !pdfWindow.closed) {
                pdfWindow.location.href = pdfUrl;
            } else if (isSafari) {
                window.location.href = pdfUrl;
            } else {
                // Build the download link ourselves instead of calling jsPDF's
                // own save(), since jsPDF's save() does its own Safari
                // sniffing internally and that can misfire on desktop.
                const link = document.createElement("a");
                link.href = pdfUrl;
                link.download = pdfFilename;
                document.body.appendChild(link);
                link.click();
                link.remove();
            }
            window.setTimeout(() => URL.revokeObjectURL(pdfUrl), 120000);
        } catch (error) {
            console.error("Could not generate mark sheet PDF:", error);
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert("Something went wrong generating the mark sheet. Please try again.");
        } finally {
            button.disabled = false;
            button.innerHTML = original;
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll(".marksheet-download-btn").forEach(button => {
            button.addEventListener("click", () => {
                downloadMarkSheet(button.dataset.marksheetType, button);
            });
        });
    });
})();