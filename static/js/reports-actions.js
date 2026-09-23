(function () {
    let activeReport = null;
    let activeStudentId = null;
    let previewMode = "individual";

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function parseRecord(button) {
        try {
            return JSON.parse(button.dataset.record || "{}");
        } catch (error) {
            console.error("Could not read report data:", error);
            return {};
        }
    }

    function selectedStudent() {
        const students = activeReport?.students || [];
        return students.find((student) => student.id === activeStudentId) || students[0];
    }

    // --- Marks pivot helpers ---
    //
    // student.assessments is a flat list of rows: { subject, type, maximum, mark, aggregate, grade, mode }
    // "type" is the real assessment period: "B.O.T.", "Mid", "E.O.T Internal", or "E.O.T External" — every
    // subject uses these same periods now. "mode" ("marks" vs "letter") is what actually separates Major
    // subjects from Other subjects, driven by each subject's compulsory flag on the backend.

    function numeric(value) {
        if (value === "" || value === null || value === undefined) return null;
        const n = Number(value);
        return Number.isFinite(n) ? n : null;
    }

    // Standard PLE-style aggregate bands. Adjust the cutoffs here if your school uses a different scale.
    function computeDivision(totalAggregate) {
        if (totalAggregate <= 12) return "1";
        if (totalAggregate <= 23) return "2";
        if (totalAggregate <= 29) return "3";
        if (totalAggregate <= 33) return "4";
        return "U";
    }

    function groupMarkRows(student) {
        const groups = {};
        (student.assessments || []).forEach((row) => {
            if (row.mode !== "marks") return;
            if (!groups[row.type]) groups[row.type] = [];
            groups[row.type].push(row);
        });
        return groups;
    }

    function schoolInitials(name) {
        const words = (name || "").trim().split(/\s+/).filter(Boolean);
        if (!words.length) return "S";
        if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
        return (words[0][0] + words[1][0]).toUpperCase();
    }

    function subjectsFromRows(rows) {
        const subjects = [];
        (rows || []).forEach((r) => {
            if (!subjects.includes(r.subject)) subjects.push(r.subject);
        });
        return subjects;
    }

    function rowFor(subject, rows) {
        return (rows || []).find((r) => r.subject === subject);
    }

    // label: "B.O.T." or "Mid". subjects: fixed column list to render (may be wider than what has data).
    // rows: whatever assessment rows exist for this period — subjects with no matching row render blank.
    function renderSimplePeriodTable(label, subjects, rows) {
        if (!subjects || !subjects.length) {
            return `
                <table class="report-period-table">
                    <thead><tr class="period-header-row"><th class="period-label">${escapeHtml(label)}</th><th>No subjects set up yet</th></tr></thead>
                </table>
            `;
        }

        let totalMark = 0, markCount = 0, totalAgg = 0, aggCount = 0;

        const markCells = subjects.map((subject) => {
            const r = rowFor(subject, rows);
            const m = r ? numeric(r.mark) : null;
            if (m !== null) { totalMark += m; markCount += 1; }
            return `<td class="report-mark-cell">${m !== null ? escapeHtml(r.mark) : ""}</td>`;
        }).join("");

        const aggCells = subjects.map((subject) => {
            const r = rowFor(subject, rows);
            const a = r ? numeric(r.aggregate) : null;
            if (a !== null) { totalAgg += a; aggCount += 1; }
            return `<td class="report-agg-cell">${a !== null ? escapeHtml(r.aggregate) : ""}</td>`;
        }).join("");

        const division = aggCount ? computeDivision(totalAgg) : "";

        return `
            <table class="report-period-table">
                <thead>
                    <tr class="period-header-row">
                        <th class="period-label">${escapeHtml(label)}</th>
                        ${subjects.map((s) => `<th>${escapeHtml(s)}</th>`).join("")}
                        <th>Total</th>
                        <th>Division</th>
                    </tr>
                </thead>
                <tbody>
                    <tr class="marks-row">
                        <th>Marks</th>
                        ${markCells}
                        <td class="report-mark-cell">${markCount ? totalMark : ""}</td>
                        <td></td>
                    </tr>
                    <tr class="aggregates-row">
                        <th>Aggregates</th>
                        ${aggCells}
                        <td class="report-agg-cell">${aggCount ? totalAgg : ""}</td>
                        <td>${division}</td>
                    </tr>
                </tbody>
            </table>
        `;
    }

    // subjects: fixed column list. internalRows/externalRows: whatever E.O.T. results exist.
    function renderEotTable(subjects, internalRows, externalRows) {
        internalRows = internalRows || [];
        externalRows = externalRows || [];

        if (!subjects || !subjects.length) {
            return `
                <table class="report-period-table report-eot-table">
                    <thead><tr class="period-header-row"><th class="period-label">E.O.T.</th><th>No subjects set up yet</th></tr></thead>
                </table>
            `;
        }

        function renderRow(label, rows) {
            let totalMark = 0, markCount = 0, totalAgg = 0, aggCount = 0;
            const cells = subjects.map((subject) => {
                const r = rowFor(subject, rows);
                const m = r ? numeric(r.mark) : null;
                const a = r ? numeric(r.aggregate) : null;
                if (m !== null) { totalMark += m; markCount += 1; }
                if (a !== null) { totalAgg += a; aggCount += 1; }
                return `<td class="report-mark-cell">${m !== null ? escapeHtml(r.mark) : ""}</td><td class="report-agg-cell">${a !== null ? escapeHtml(r.aggregate) : ""}</td>`;
            }).join("");
            const division = aggCount ? computeDivision(totalAgg) : "";
            return `
                <tr>
                    <th>${escapeHtml(label)}</th>
                    ${cells}
                    <td class="report-mark-cell">${markCount ? totalMark : ""}</td>
                    <td class="report-agg-cell">${aggCount ? totalAgg : ""}</td>
                    <td>${division}</td>
                </tr>
            `;
        }

        return `
            <table class="report-period-table report-eot-table">
                <thead>
                    <tr class="period-header-row">
                        <th class="period-label">E.O.T.</th>
                        ${subjects.map((s) => `<th colspan="2">${escapeHtml(s)}</th>`).join("")}
                        <th colspan="2">Total</th>
                        <th rowspan="2">Division</th>
                    </tr>
                    <tr class="sub-header-row">
                        <th class="marks-subheader-label">Marks</th>
                        ${subjects.map(() => `<th>MKS</th><th>AGG</th>`).join("")}
                        <th>MKS</th><th>AGG</th>
                    </tr>
                </thead>
                <tbody>
                    ${renderRow("Internal", internalRows)}
                    ${renderRow("External", externalRows)}
                </tbody>
            </table>
        `;
    }

    // A digital signature (uploaded photo of a handwritten signature) when
    // the staff member has one, otherwise a blank line for signing by hand.
    function signatureBlock(signatureUrl) {
        return signatureUrl
            ? `<span class="report-signature-label">Signature:</span> <img class="report-signature-img" src="${escapeHtml(signatureUrl)}" alt="Signature">`
            : `<span class="report-signature-label">Signature:</span> <span class="report-signature-line"></span>`;
    }

    // Which assessment period(s) speak for "the grade on this report", in
    // priority order — mirrors the period shown in the main subjects table
    // above, so an Other subject shows one grade, not one row per period.
    function periodPriorityForReport(reportType) {
        if (reportType === "Beginning of term") return ["B.O.T."];
        if (reportType === "Mid-term") return ["Mid"];
        if (reportType === "End of term") return ["E.O.T External", "E.O.T Internal"];
        return ["E.O.T External", "E.O.T Internal", "Mid", "B.O.T."];
    }

    // One row per subject — matches the template's 3-column layout
    // (Other subjects / Grade / Teacher's assessment), picking whichever
    // period is relevant to the report being viewed.
    function otherSubjectRows(student, reportType) {
        const rows = (student.assessments || []).filter((row) => row.mode === "letter");
        if (!rows.length) return "";

        const priority = periodPriorityForReport(reportType);
        // A period that isn't in this report's priority list (indexOf === -1)
        // must rank *below* every real match, not above it — otherwise the
        // very first period ever entered for a subject (typically B.O.T.)
        // wins forever, since -1 is numerically less than any real index.
        const priorityRank = (type) => {
            const idx = priority.indexOf(type);
            return idx === -1 ? Infinity : idx;
        };
        const bySubject = {};
        rows.forEach((row) => {
            const existing = bySubject[row.subject];
            if (!existing || priorityRank(row.type) < priorityRank(existing.type)) {
                bySubject[row.subject] = row;
            }
        });
        const pickedRows = subjectsFromRows(rows).map((subject) => bySubject[subject]).filter(Boolean);

        return `
            <table class="report-other-subjects-table">
                <thead><tr><th>Other subjects</th><th>Grade</th><th>Teacher's assessment</th></tr></thead>
                <tbody>
                    ${pickedRows.map((row) => `
                        <tr>
                            <td>${escapeHtml(row.subject)}</td>
                            <td>${escapeHtml(row.grade || "—")}</td>
                            <td>${escapeHtml(row.remark || "—")}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;
    }

    // --- Shared brand header/footer (used by both the academic report card
    // and the attendance summary page) ---

    function reportBrandHeader() {
        const crestInner = SCHOOL_INFO.logo_url
            ? `<img src="${SCHOOL_INFO.logo_url}" alt="${escapeHtml(SCHOOL_NAME)} logo">`
            : escapeHtml(schoolInitials(SCHOOL_NAME));
        return `
            <div class="report-card-brand">
                <div>
                    <p class="report-school-name">${escapeHtml(SCHOOL_NAME)}</p>
                    ${SCHOOL_INFO.type ? `<p class="report-school-type">${escapeHtml(SCHOOL_INFO.type)}</p>` : ""}
                </div>
                <div class="report-crest">${crestInner}</div>
            </div>
        `;
    }

    function reportBrandFooter() {
        const contactLine1 = [
            SCHOOL_INFO.address,
            SCHOOL_INFO.phone ? `Tel: ${SCHOOL_INFO.phone}` : "",
        ].filter(Boolean).map(escapeHtml).join(" &middot; ");

        const contactLine2 = [
            SCHOOL_INFO.email ? `Email: ${SCHOOL_INFO.email}` : "",
            SCHOOL_INFO.website ? `Website: ${SCHOOL_INFO.website}` : "",
        ].filter(Boolean).map(escapeHtml).join(" &middot; ");

        return `
            <div class="report-card-footer">
                <div class="report-flag-badge">
                    <img class="report-flag-img" src="/static/images/school/uganda-flag.png" alt="Uganda flag">
                    <div class="report-flag-text">
                        <strong>UGANDA</strong>
                        <span class="report-flag-curriculum">National Curriculum</span>
                        ${SCHOOL_INFO.reg_no ? `<span class="report-reg-no">REG No: ${escapeHtml(SCHOOL_INFO.reg_no)}</span>` : ""}
                    </div>
                </div>
                ${(contactLine1 || contactLine2) ? `
                    <p class="report-contact-line">
                        ${contactLine1}${contactLine1 && contactLine2 ? "<br>" : ""}${contactLine2}
                    </p>` : ""}
            </div>
        `;
    }

    // --- Attendance report: a simple summary table (per class + whole
    // school), then the absentee names listed per class. No per-student
    // sidebar or Individual/All-in-One split — this report isn't per-student.

    function renderAttendanceReportCard(record) {
        const summary = record.attendance_summary || { classes: [], whole_school: { total: 0, absent: 0, present: 0 } };
        const classes = summary.classes || [];
        const wholeSchool = summary.whole_school || { total: 0, absent: 0, present: 0 };

        const summaryRows = classes.map((c) => `
            <tr>
                <td>${escapeHtml(c.class_name)}</td>
                <td>${c.total}</td>
                <td>${c.absent}</td>
                <td>${c.present}</td>
            </tr>
        `).join("");

        const absenteeSections = classes.map((c) => `
            <div class="attendance-absent-group">
                <p class="attendance-absent-class">${escapeHtml(c.class_name)} <span>(${c.absent} absent)</span></p>
                ${c.absent_names && c.absent_names.length
                    ? `<ul class="attendance-absent-names">${c.absent_names.map((name) => `<li>${escapeHtml(name)}</li>`).join("")}</ul>`
                    : `<p class="report-empty-note">No absences recorded.</p>`}
            </div>
        `).join("");

        return `
            <article class="report-card-page attendance-report-page">
                <div class="report-card-frame">
                    ${reportBrandHeader()}

                    <div class="report-card-title-row">
                        <p class="report-class-term">
                            <span><strong>Term:</strong> <span class="report-highlight">${escapeHtml(CURRENT_TERM_NAME || "—")}</span></span>
                            <span><strong>Date:</strong> <span class="report-highlight">${escapeHtml(summary.date || record.created_at || "—")}</span></span>
                        </p>
                        <h3>Attendance Report</h3>
                    </div>

                    <table class="attendance-summary-table">
                        <thead>
                            <tr><th>Class</th><th>Total</th><th>Absent</th><th>Present</th></tr>
                        </thead>
                        <tbody>
                            ${summaryRows || `<tr><td colspan="4" class="report-empty-note">No classes in this report.</td></tr>`}
                        </tbody>
                        <tfoot>
                            <tr class="attendance-summary-total-row">
                                <td>Whole School</td>
                                <td>${wholeSchool.total}</td>
                                <td>${wholeSchool.absent}</td>
                                <td>${wholeSchool.present}</td>
                            </tr>
                        </tfoot>
                    </table>

                    <div class="attendance-absent-list">
                        <p class="attendance-absent-list-title">Absentees</p>
                        ${absenteeSections || `<p class="report-empty-note">No classes in this report.</p>`}
                    </div>

                    ${reportBrandFooter()}
                </div>
            </article>
        `;
    }

    // --- Mini slip: the compact B.O.T./Mid-term take-home slip, replacing
    // the full report card for those two report types. Two copies of the
    // same slip print on one physical page — one to keep, one to send home.

    function computePeriodTotals(subjects, rows) {
        let totalMark = 0, markCount = 0, totalAgg = 0, aggCount = 0;
        subjects.forEach((subject) => {
            const r = rowFor(subject, rows);
            const m = r ? numeric(r.mark) : null;
            const a = r ? numeric(r.aggregate) : null;
            if (m !== null) { totalMark += m; markCount += 1; }
            if (a !== null) { totalAgg += a; aggCount += 1; }
        });
        return { totalMark, markCount, totalAgg, aggCount, division: aggCount ? computeDivision(totalAgg) : "" };
    }

    function renderMiniSlipSection(titleLabel, subjects, rows) {
        rows = rows || [];
        if (!subjects.length) return "";
        const totals = computePeriodTotals(subjects, rows);
        return `
            <p class="report-mini-title">${escapeHtml(titleLabel)}</p>
            <table class="report-mini-table">
                <thead>
                    <tr>
                        ${subjects.map((s) => `<th class="report-mini-subject">${escapeHtml(s)}</th><th class="report-mini-agg-label">AGG</th>`).join("")}
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        ${subjects.map((subject) => {
                            const r = rowFor(subject, rows);
                            return `<td>${r && r.mark !== "" ? escapeHtml(r.mark) : ""}</td><td class="report-mini-agg-value">${r && r.aggregate !== "" ? escapeHtml(r.aggregate) : ""}</td>`;
                        }).join("")}
                    </tr>
                </tbody>
            </table>
            <table class="report-mini-totals">
                <tr>
                    <td><strong>Total marks:</strong> ${totals.markCount ? totals.totalMark : ""}</td>
                    <td class="report-mini-total-agg"><strong>TOTAL AGG:</strong> ${totals.aggCount ? totals.totalAgg : ""}</td>
                    <td><strong>Division:</strong> ${totals.division}</td>
                </tr>
            </table>
        `;
    }

    function renderMiniSlip(student) {
        const groups = groupMarkRows(student);
        const mainSubjects = student.main_subjects || [];
        const botTitle = `BEGINNING OF TERM ${TERM_TITLE_WORD} REPORT ${TERM_TITLE_YEAR}.`;
        const midTitle = `MID-TERM ${TERM_TITLE_WORD} REPORT ${TERM_TITLE_YEAR}.`;

        return `
            <div class="report-mini-slip">
                ${reportBrandHeader()}
                <table class="report-mini-meta">
                    <tr>
                        <th>Name:</th><td>${escapeHtml((student.name || "").toUpperCase())}</td>
                        <th>Class:</th><td>${escapeHtml(student.class_name)}</td>
                        <th>Date:</th><td>${escapeHtml(activeReport.created_at || activeReport.published_at || "—")}</td>
                    </tr>
                </table>

                ${renderMiniSlipSection(botTitle, mainSubjects, groups["B.O.T."])}
                ${renderMiniSlipSection(midTitle, mainSubjects, groups["Mid"])}

                <div class="report-mini-comment">
                    <p><span class="report-mini-comment-label">Class teacher's comment:</span> ${escapeHtml(student.comments["Class teacher"] || "—")}</p>
                    <div class="report-mini-signature-row">
                        <span><strong>Class teacher's name:</strong> ${escapeHtml(student.class_teacher || "—")}</span>
                        <span class="report-signature">${signatureBlock(student.class_teacher_signature_url)}</span>
                    </div>
                </div>
            </div>
        `;
    }

    function renderMiniSlipPage(studentA, studentB) {
        return `
            <article class="report-card-page report-mini-page">
                ${renderMiniSlip(studentA)}
                ${studentB ? `
                    <div class="report-mini-cutline"><span>✂ cut here</span></div>
                    ${renderMiniSlip(studentB)}
                ` : ""}
            </article>
        `;
    }

    function isMiniSlipReport() {
        const reportType = activeReport?.report_type;
        return reportType === "Beginning of term" || reportType === "Mid-term";
    }

    // Every page pairs two different students' slips, cut in half. Pairing
    // is done within each class (grouping by class_name first) so a page
    // never mixes students from two different classes — if a class has an
    // odd number of students, its last slip gets a page to itself.
    function miniSlipPairs(students) {
        const byClass = new Map();
        students.forEach((student) => {
            const key = student.class_name || "";
            if (!byClass.has(key)) byClass.set(key, []);
            byClass.get(key).push(student);
        });

        const pairs = [];
        byClass.forEach((classStudents) => {
            for (let i = 0; i < classStudents.length; i += 2) {
                pairs.push([classStudents[i], classStudents[i + 1] || null]);
            }
        });
        return pairs;
    }

    function miniSlipPairForStudent(students, studentId) {
        const pairs = miniSlipPairs(students);
        const match = pairs.find(([a, b]) => a.id === studentId || (b && b.id === studentId));
        if (match) return match;
        return [students.find((s) => s.id === studentId) || students[0], null];
    }

    function renderReportCard(student) {
        const reportType = activeReport.report_type;

        const groups = groupMarkRows(student);
        const mainSubjects = student.main_subjects || [];

        let periodTablesHtml = "";
        if (reportType === "End of term") {
            // End of term always shows all three sections, even with no marks recorded yet —
            // columns come from the class's registered subjects, not from whatever data exists.
            periodTablesHtml += renderSimplePeriodTable("B.O.T.", mainSubjects, groups["B.O.T."]);
            periodTablesHtml += renderSimplePeriodTable("Mid", mainSubjects, groups["Mid"]);
            periodTablesHtml += renderEotTable(mainSubjects, groups["E.O.T Internal"], groups["E.O.T External"]);
        } else {
            // Beginning of term / Mid-term remain exactly as their existing mini-slip layout.
            ["B.O.T.", "Mid"].forEach((type) => {
                const rows = groups[type] || [];
                if (rows.length) periodTablesHtml += renderSimplePeriodTable(type, subjectsFromRows(rows), rows);
            });
            if ((groups["E.O.T Internal"] || []).length || (groups["E.O.T External"] || []).length) {
                const eotSubjects = subjectsFromRows([...(groups["E.O.T Internal"] || []), ...(groups["E.O.T External"] || [])]);
                periodTablesHtml += renderEotTable(eotSubjects, groups["E.O.T Internal"], groups["E.O.T External"]);
            }
        }
        if (!periodTablesHtml) {
            periodTablesHtml = '<p class="report-empty-note">No marks recorded for this period yet.</p>';
        }

        const otherSubjectsHtml = otherSubjectRows(student, reportType);

        const watermarkInner = SCHOOL_INFO.logo_url
            ? `<img src="${SCHOOL_INFO.logo_url}" alt="">`
            : `<div class="report-watermark-placeholder"></div>`;

        // End-of-term is intentionally a TWO-PAGE report for every student.
        // Page 1 contains the report identity/details and grading scale.
        // Page 2 starts at B.O.T. and continues through the next-term statement.
        // B.O.T. and Mid-term report types are NOT changed here; their existing
        // mini-slip rendering remains exactly as it was.
        if (reportType === "End of term") {
            return `
                <article class="report-card-page report-eot-page report-eot-page-one">
                    <div class="report-card-frame">
                        ${reportBrandHeader()}

                        <div class="report-card-title-row">
                            <p class="report-class-term">
                                <span><strong>Class:</strong> <span class="report-highlight">${escapeHtml(student.class_name)}</span></span>
                                <span><strong>Term:</strong> <span class="report-highlight">${escapeHtml(CURRENT_TERM_NAME || "—")}</span></span>
                            </p>
                            <h3>${escapeHtml(reportType)} Report Card</h3>
                        </div>

                        <div class="report-meta-wrap">
                            <div class="report-meta-watermark">${watermarkInner}</div>
                            <table class="report-meta-table">
                                <tr><th>Pupil's name</th><td>${escapeHtml((student.name || "").toUpperCase())}</td></tr>
                                <tr><th>Date of birth</th><td>${escapeHtml(student.date_of_birth || "—")}</td></tr>
                                <tr><th>Date of enrollment</th><td>${escapeHtml(student.enrollment_date || "—")}</td></tr>
                                <tr><th>LIN</th><td>${escapeHtml(student.lin || "")}</td></tr>
                                <tr><th>Class teacher</th><td>${escapeHtml(student.class_teacher || "—")}</td></tr>
                                <tr><th>Date</th><td>${escapeHtml(activeReport.created_at || activeReport.published_at || "—")}</td></tr>
                            </table>
                        </div>

                        <div class="report-grading-scale">
                            <p class="report-grading-scale-title">Grading scale</p>
                            <p>A: Well above the expected standard of the term.</p>
                            <p>B: Above the expected standard of the term.</p>
                            <p>C: At the expected standard of the term.</p>
                            <p>D: Below the expected standard of the term.</p>
                            <p>E: Well below the expected standard of the term.</p>
                        </div>

                        ${reportBrandFooter()}
                    </div>
                </article>

                <article class="report-card-page report-eot-page report-eot-page-two">
                    <div class="report-card-frame">
                        <div class="report-period-tables">${periodTablesHtml}</div>

                        ${otherSubjectsHtml}

                        <div class="report-comments">
                            <div class="report-comment-row">
                                <p><span class="report-comment-label">Class teacher's general comment:</span> ${escapeHtml(student.comments["Class teacher"] || "—")}</p>
                                <p class="report-signature">${signatureBlock(student.class_teacher_signature_url)}</p>
                            </div>
                            <div class="report-comment-row">
                                <p><span class="report-comment-label">Head teacher's comment:</span> ${escapeHtml(student.comments["Head teacher"] || "—")}</p>
                                <p class="report-signature">${signatureBlock(HEAD_TEACHER.signature_url)}</p>
                            </div>
                        </div>

                        <p class="report-next-term">Next term commences on: <strong>${escapeHtml(NEXT_TERM_START || "—")}</strong></p>

                        ${reportBrandFooter()}
                    </div>
                </article>
            `;
        }

        // Existing layout for all other report types is preserved.
        return `
            <article class="report-card-page">
                <div class="report-card-frame">
                    ${reportBrandHeader()}

                    <div class="report-card-title-row">
                        <p class="report-class-term">
                            <span><strong>Class:</strong> <span class="report-highlight">${escapeHtml(student.class_name)}</span></span>
                            <span><strong>Term:</strong> <span class="report-highlight">${escapeHtml(CURRENT_TERM_NAME || "—")}</span></span>
                        </p>
                        <h3>${escapeHtml(reportType)} Report Card</h3>
                    </div>

                    <div class="report-meta-wrap">
                        <div class="report-meta-watermark">${watermarkInner}</div>
                        <table class="report-meta-table">
                            <tr><th>Pupil's name</th><td>${escapeHtml((student.name || "").toUpperCase())}</td></tr>
                            <tr><th>Date of birth</th><td>${escapeHtml(student.date_of_birth || "—")}</td></tr>
                            <tr><th>Date of enrollment</th><td>${escapeHtml(student.enrollment_date || "—")}</td></tr>
                            <tr><th>LIN</th><td>${escapeHtml(student.lin || "")}</td></tr>
                            <tr><th>Class teacher</th><td>${escapeHtml(student.class_teacher || "—")}</td></tr>
                            <tr><th>Date</th><td>${escapeHtml(activeReport.created_at || activeReport.published_at || "—")}</td></tr>
                        </table>
                    </div>

                    <div class="report-grading-scale">
                        <p class="report-grading-scale-title">Grading scale</p>
                        <p>A: Well above the expected standard of the term.</p>
                        <p>B: Above the expected standard of the term.</p>
                        <p>C: At the expected standard of the term.</p>
                        <p>D: Below the expected standard of the term.</p>
                        <p>E: Well below the expected standard of the term.</p>
                    </div>

                    <div class="report-period-tables">${periodTablesHtml}</div>

                    ${otherSubjectsHtml}

                    <div class="report-comments">
                        <div class="report-comment-row">
                            <p><span class="report-comment-label">Class teacher's general comment:</span> ${escapeHtml(student.comments["Class teacher"] || "—")}</p>
                            <p class="report-signature">${signatureBlock(student.class_teacher_signature_url)}</p>
                        </div>
                        <div class="report-comment-row">
                            <p><span class="report-comment-label">Head teacher's comment:</span> ${escapeHtml(student.comments["Head teacher"] || "—")}</p>
                            <p class="report-signature">${signatureBlock(HEAD_TEACHER.signature_url)}</p>
                        </div>
                    </div>

                    <p class="report-next-term">Next term commences on: <strong>${escapeHtml(NEXT_TERM_START || "—")}</strong></p>

                    ${reportBrandFooter()}
                </div>
            </article>
        `;
    }

    function renderStudentList() {
        const query = document.getElementById("reportStudentSearch").value.toLowerCase();
        const list = document.getElementById("reportStudentList");
        const students = (activeReport.students || []).filter((student) => student.name.toLowerCase().includes(query));
        list.innerHTML = students.length ? students.map((student) => `
            <button type="button" class="report-student-item ${student.id === activeStudentId ? "active" : ""}" data-student-id="${student.id}">
                <i class="ti ti-file-text"></i>
                <span>
                    <strong>${escapeHtml(student.name)}</strong>
                    <small>${escapeHtml(activeReport.created_at || activeReport.published_at)} · Generated</small>
                </span>
            </button>
        `).join("") : '<p class="form-subheading">No students found.</p>';
    }

    function renderPreview() {
        const documentEl = document.getElementById("reportDocument");

        if (activeReport?.report_type === "Attendance report") {
            documentEl.innerHTML = renderAttendanceReportCard(activeReport);
            document.getElementById("reportPageCount").textContent = "1 Page";
            return;
        }

        const students = activeReport?.students || [];
        if (!students.length) {
            documentEl.innerHTML = '<p class="form-subheading">No generated reports are available yet.</p>';
            document.getElementById("reportPageCount").textContent = "0 Pages";
            return;
        }
        if (isMiniSlipReport()) {
            if (previewMode === "all") {
                const pairs = miniSlipPairs(students);
                documentEl.innerHTML = pairs.map(([a, b]) => renderMiniSlipPage(a, b)).join("");
                document.getElementById("reportPageCount").textContent = `${pairs.length} Pages`;
            } else {
                const [a, b] = miniSlipPairForStudent(students, selectedStudent().id);
                documentEl.innerHTML = renderMiniSlipPage(a, b);
                document.getElementById("reportPageCount").textContent = "1 Page";
            }
            renderStudentList();
            return;
        }

        if (previewMode === "all") {
            documentEl.innerHTML = students.map(renderReportCard).join("");
            document.getElementById("reportPageCount").textContent = `${students.length} Pages`;
        } else {
            documentEl.innerHTML = renderReportCard(selectedStudent());
            document.getElementById("reportPageCount").textContent = "1 Page";
        }
        renderStudentList();
    }

    function openPreview(record) {
        activeReport = record;
        const isAttendance = record.report_type === "Attendance report";

        activeStudentId = (!isAttendance && record.students && record.students[0] && record.students[0].id) || null;
        previewMode = "individual";
        document.getElementById("reportPreviewTitle").textContent = isAttendance
            ? record.report_type
            : `${record.class_name} - ${record.report_type}`;
        document.getElementById("reportPreviewSubtitle").textContent = `Generated on: ${record.created_at || record.published_at || "—"}`;
        document.getElementById("reportStudentSearch").value = "";
        document.querySelectorAll(".report-preview-tab").forEach((tab) => {
            tab.classList.toggle("active", tab.dataset.previewMode === "individual");
        });

        // Attendance reports aren't per-student — hide the sidebar and the
        // Individual/All-in-One tabs, since neither applies to this format.
        // Also collapse the sidebar's grid column so the document area uses
        // the full width instead of leaving an empty 300px gap.
        document.querySelector(".report-student-panel").hidden = isAttendance;
        document.querySelector(".report-preview-tabs").hidden = isAttendance;
        document.querySelector(".report-preview-body").classList.toggle("no-sidebar", isAttendance);

        document.getElementById("reportPreviewOverlay").classList.add("open");
        renderPreview();
    }

    function openPublish(record) {
        const form = document.getElementById("publishReportForm");
        form.action = `${REPORT_URL_BASE}/${record.id}/publish`;
        form.reset();
        form.querySelector('[name="publish_here"]').checked = true;
        document.getElementById("publish-email-field").hidden = true;
        openModal("publishReportModal");
    }

    function openDeleteConfirm(formId, label) {
        document.getElementById("confirmDeleteText").textContent =
            `This will permanently remove ${label}. This can't be undone.`;
        document.getElementById("confirmDeleteBtn").onclick = function () {
            document.getElementById(formId).submit();
        };
        openModal("confirmDeleteModal");
    }

    document.addEventListener("click", (event) => {
        const actionButton = event.target.closest("[data-report-action]");
        if (actionButton) {
            const action = actionButton.dataset.reportAction;
            if (action === "preview") openPreview(parseRecord(actionButton));
            if (action === "publish") openPublish(parseRecord(actionButton));
            if (action === "delete") openDeleteConfirm(actionButton.dataset.formId, actionButton.dataset.label || "this report");
            return;
        }

        const studentButton = event.target.closest(".report-student-item");
        if (studentButton) {
            activeStudentId = Number(studentButton.dataset.studentId);
            previewMode = "individual";
            document.querySelectorAll(".report-preview-tab").forEach((tab) => {
                tab.classList.toggle("active", tab.dataset.previewMode === "individual");
            });
            renderPreview();
        }
    });

    document.addEventListener("change", (event) => {
        if (event.target.id === "publish-email-toggle") {
            document.getElementById("publish-email-field").hidden = !event.target.checked;
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        document.getElementById("reportPreviewClose").addEventListener("click", () => {
            document.getElementById("reportPreviewOverlay").classList.remove("open");
        });
        document.getElementById("reportStudentSearch").addEventListener("input", renderStudentList);
        document.querySelectorAll(".report-preview-tab").forEach((tab) => {
            tab.addEventListener("click", () => {
                previewMode = tab.dataset.previewMode;
                document.querySelectorAll(".report-preview-tab").forEach((item) => item.classList.toggle("active", item === tab));
                renderPreview();
            });
        });
        document.getElementById("reportDownloadBtn").addEventListener("click", () => {
            downloadReportPdf();
        });
    });

    // Turn the currently rendered preview into an actual PDF file download.
    // The preview is cloned into a top-level helper so it is not affected by
    // the fixed preview overlay or its scrolling document area.
    async function downloadReportPdf() {
        const source = document.getElementById("reportDocument");
        const downloadBtn = document.getElementById("reportDownloadBtn");

        // Ignore repeat clicks while a download is already being generated —
        // without this guard a second tap while html2canvas is still working
        // can leave the button permanently stuck on its spinner icon.
        if (downloadBtn.disabled) return;

        // Safari — on iPhone/iPad AND on the Mac desktop app — blocks the
        // window jsPDF's own save() tries to open once it runs after the
        // async canvas render, because by then the browser no longer treats
        // it as a direct result of the click. This is a WebKit/Safari
        // restriction, not a phone-vs-laptop one, so it has to be detected by
        // browser engine rather than by screen size or touch support alone.
        // Open a blank tab synchronously, in the same click, for every
        // Safari build, then fill it in once the PDF is ready.
        const ua = navigator.userAgent;
        const isIOS = /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
        const isSafari = isIOS || (/Safari/i.test(ua) && !/Chrome|CriOS|FxiOS|Edg|Android/i.test(ua));
        const pdfWindow = isSafari ? window.open("about:blank", "_blank") : null;

        if (!source || !activeReport || !source.innerHTML.trim()) {
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert("There is no report content to download.");
            return;
        }

        if (typeof html2canvas !== "function") {
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert("The PDF renderer is not loaded. Please refresh the page and try again.");
            return;
        }

        if (!window.jspdf || !window.jspdf.jsPDF) {
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert("The PDF library is not loaded. Please refresh the page and try again.");
            return;
        }

        const pages = Array.from(source.querySelectorAll(".report-card-page"));
        if (!pages.length) {
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert("There is no report page to download.");
            return;
        }

        const originalIcon = downloadBtn.innerHTML;
        downloadBtn.disabled = true;
        downloadBtn.innerHTML = '<i class="ti ti-loader-2"></i>';

        // Everything below — including building the jsPDF instance — now runs
        // inside the try/finally so any failure always re-enables the button
        // instead of leaving it stuck spinning forever.
        const A4_WIDTH = 595.28;
        const A4_HEIGHT = 841.89;
        const PAGE_PADDING = 0;
        const MAX_WIDTH = A4_WIDTH;
        const MAX_HEIGHT = A4_HEIGHT;

        try {
            const filenameBase = (
                activeReport.class_name
                    ? `${activeReport.class_name}-${activeReport.report_type}`
                    : activeReport.report_type || "report"
            ).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

            const { jsPDF } = window.jspdf;
            const pdf = new jsPDF({
                unit: "pt",
                format: "a4",
                orientation: "portrait",
                compress: true,
            });

            // Wait until the currently visible report has finished laying out.
            await new Promise((resolve) => requestAnimationFrame(() =>
                requestAnimationFrame(resolve)
            ));
            if (document.fonts && document.fonts.ready) await document.fonts.ready;

            for (let index = 0; index < pages.length; index += 1) {
                const page = pages[index];

                // Wait for all images on this report before capturing it.
                const images = Array.from(page.querySelectorAll("img"));
                await Promise.all(images.map((img) => {
                    if (img.complete && img.naturalWidth > 0) return Promise.resolve();
                    return new Promise((resolve) => {
                        const done = () => {
                            img.removeEventListener("load", done);
                            img.removeEventListener("error", done);
                            resolve();
                        };
                        img.addEventListener("load", done, { once: true });
                        img.addEventListener("error", done, { once: true });
                    });
                }));

                // Capture the report exactly as it is displayed. We do NOT
                // alter the B.O.T./Mid-term mini-slip layout; the whole
                // physical slip page is simply scaled proportionally to fit A4.
                const canvas = await html2canvas(page, {
                    scale: 2,
                    useCORS: true,
                    allowTaint: false,
                    backgroundColor: "#ffffff",
                    logging: false,
                    scrollX: 0,
                    scrollY: -window.scrollY,
                    windowWidth: document.documentElement.clientWidth,
                    onclone: (clonedDocument) => {
                        // PDF-only fixes: keep the on-screen design unchanged,
                        // but make gradient text render reliably in canvas/PDF.
                        clonedDocument.querySelectorAll(".report-school-name").forEach((el, schoolIndex) => {
                            // html2canvas does not reliably reproduce CSS gradient text
                            // (background-clip:text). Keep the PDF visually identical to
                            // the preview by replacing only the PDF clone's school-name
                            // text with an inline SVG using the EXACT same gradient stops.
                            const text = (el.textContent || "").trim();
                            if (!text) return;

                            const cs = clonedDocument.defaultView.getComputedStyle(el);
                            const fontSize = parseFloat(cs.fontSize) || 27;
                            const fontWeight = cs.fontWeight || "800";
                            const fontFamily = cs.fontFamily || "Arial, sans-serif";
                            const letterSpacing = cs.letterSpacing || "normal";
                            const lineHeight = parseFloat(cs.lineHeight) || fontSize * 1.2;

                            const svgNS = "http://www.w3.org/2000/svg";
                            const svg = clonedDocument.createElementNS(svgNS, "svg");
                            const width = Math.max(el.getBoundingClientRect().width, 1);
                            const height = Math.max(el.getBoundingClientRect().height, lineHeight);
                            svg.setAttribute("width", width);
                            svg.setAttribute("height", height);
                            svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
                            svg.style.display = "block";
                            svg.style.width = `${width}px`;
                            svg.style.height = `${height}px`;
                            svg.style.overflow = "visible";

                            const defs = clonedDocument.createElementNS(svgNS, "defs");
                            const gradient = clonedDocument.createElementNS(svgNS, "linearGradient");
                            const gradientId = `schoolNameGradientPdf_${schoolIndex}`;
                            gradient.setAttribute("id", gradientId);
                            gradient.setAttribute("x1", "0%");
                            gradient.setAttribute("y1", "0%");
                            gradient.setAttribute("x2", "100%");
                            gradient.setAttribute("y2", "0%");

                            [
                                ["0%", "#E4572E"],
                                ["20%", "#7B4FA1"],
                                ["40%", "#2E9BD6"],
                                ["60%", "#7CB518"],
                                ["80%", "#F2A623"],
                                ["100%", "#E4572E"]
                            ].forEach(([offset, color]) => {
                                const stop = clonedDocument.createElementNS(svgNS, "stop");
                                stop.setAttribute("offset", offset);
                                stop.setAttribute("stop-color", color);
                                gradient.appendChild(stop);
                            });

                            defs.appendChild(gradient);
                            svg.appendChild(defs);

                            const t = clonedDocument.createElementNS(svgNS, "text");
                            t.setAttribute("x", "0");
                            t.setAttribute("y", String(Math.max(fontSize, (height + fontSize * 0.72) / 2)));
                            t.setAttribute("fill", `url(#${gradientId})`);
                            t.setAttribute("font-size", String(fontSize));
                            t.setAttribute("font-weight", fontWeight);
                            t.setAttribute("font-family", fontFamily);
                            if (letterSpacing !== "normal") t.setAttribute("letter-spacing", letterSpacing);
                            t.textContent = text;
                            svg.appendChild(t);

                            el.textContent = "";
                            el.style.background = "none";
                            el.style.backgroundImage = "none";
                            el.style.webkitBackgroundClip = "initial";
                            el.style.backgroundClip = "initial";
                            el.style.webkitTextFillColor = "initial";
                            el.style.color = "transparent";
                            el.appendChild(svg);
                        });

                        // End-of-term is intentionally two A4 pages. The first
                        // page contains the school header/details/grading scale and
                        // the second page starts at B.O.T. Keep both page sections
                        // together and let the PDF scaler fit each one independently.
                        clonedDocument.querySelectorAll(".report-eot-page").forEach((el) => {
                            el.style.breakInside = "avoid";
                            el.style.pageBreakInside = "avoid";
                            el.style.minHeight = "0";
                        });

                        // Keep the End-of-Term Division column stable in the
                        // PDF renderer without changing the visible report.
                        // The Division header is a rowspan cell. html2canvas can
                        // sometimes let the second header row paint over the
                        // lower half of a rowspan cell, so give that PDF-only
                        // header an explicit blue fill that covers the whole cell.
                        clonedDocument.querySelectorAll(".report-eot-table").forEach((table) => {
                            table.style.tableLayout = "fixed";

                            const divisionCells = table.querySelectorAll("th:last-child, td:last-child");
                            divisionCells.forEach((cell) => {
                                cell.style.width = "9%";
                                cell.style.minWidth = "48px";
                                cell.style.whiteSpace = "nowrap";
                                cell.style.textAlign = "center";
                            });

                            const divisionHeader = table.querySelector(
                                "thead tr.period-header-row th[rowspan='2']:last-child"
                            );

                            if (divisionHeader) {
                                const BLUE = "#29B6E8";

                                divisionHeader.style.background = BLUE;
                                divisionHeader.style.backgroundColor = BLUE;
                                divisionHeader.style.verticalAlign = "middle";
                                divisionHeader.style.position = "relative";
                                divisionHeader.style.overflow = "hidden";

                                // Add a PDF-only full-cell blue layer. This sits
                                // above the second header-row background and
                                // below the Division text.
                                const fill = clonedDocument.createElement("div");
                                fill.style.position = "absolute";
                                fill.style.left = "0";
                                fill.style.top = "0";
                                fill.style.right = "0";
                                fill.style.bottom = "0";
                                fill.style.width = "100%";
                                fill.style.height = "100%";
                                fill.style.backgroundColor = BLUE;
                                fill.style.zIndex = "0";
                                fill.style.pointerEvents = "none";

                                const label = clonedDocument.createElement("span");
                                label.textContent = divisionHeader.textContent.trim();
                                label.style.position = "relative";
                                label.style.zIndex = "1";
                                label.style.display = "inline-block";

                                divisionHeader.textContent = "";
                                divisionHeader.appendChild(fill);
                                divisionHeader.appendChild(label);
                            }
                        });
                    },
                });

                const canvasWidth = canvas.width;
                const canvasHeight = canvas.height;
                if (!canvasWidth || !canvasHeight) {
                    throw new Error(`Report page ${index + 1} produced an empty image.`);
                }

                // Keep the original width scaling exactly as before. For BOTH
                // End-of-Term pages, stretch ONLY the height so each page fills A4
                // vertically without changing its width. All other pages keep their
                // normal proportional scaling.
                const ratio = Math.min(
                    MAX_WIDTH / canvasWidth,
                    MAX_HEIGHT / canvasHeight
                );

                const isEotPage =
                    activeReport.report_type === "End of term" &&
                    page.classList.contains("report-eot-page");

                // For BOTH End-of-Term pages, keep the width scaling exactly
                // as before and scale ONLY the height to fill the full A4 page.
                // This preserves the report's horizontal proportions while
                // removing the unnecessary vertical white space.
                const imageWidth = canvasWidth * ratio;
                const imageHeight = isEotPage
                    ? MAX_HEIGHT
                    : canvasHeight * ratio;
                const x = (A4_WIDTH - imageWidth) / 2;
                const y = isEotPage
                    ? 0
                    : (A4_HEIGHT - imageHeight) / 2;

                if (index > 0) pdf.addPage("a4", "portrait");
                pdf.setFillColor(255, 255, 255);
                pdf.rect(0, 0, A4_WIDTH, A4_HEIGHT, "F");
                pdf.addImage(
                    canvas.toDataURL("image/jpeg", 0.98),
                    "JPEG",
                    x,
                    y,
                    imageWidth,
                    imageHeight,
                    undefined,
                    "FAST"
                );
            }

            const pdfFilename = `${filenameBase || "report"}.pdf`;
            const pdfBlob = pdf.output("blob");
            const pdfUrl = URL.createObjectURL(pdfBlob);

            if (pdfWindow && !pdfWindow.closed) {
                // Safari (mobile or desktop): the tab was opened synchronously
                // from the user's click, so load the generated PDF into that tab.
                pdfWindow.location.href = pdfUrl;
            } else if (isSafari) {
                // The browser blocked the new tab — fall back to navigating the
                // current tab to the PDF rather than silently doing nothing.
                window.location.href = pdfUrl;
            } else {
                // Chrome, Firefox, Edge (desktop and Android): a plain blob
                // download link is the most reliable path. We build this
                // ourselves instead of calling jsPDF's own save(), since
                // jsPDF's save() does its own Safari sniffing internally and
                // that's what was causing this to misfire on desktop.
                const link = document.createElement("a");
                link.href = pdfUrl;
                link.download = pdfFilename;
                document.body.appendChild(link);
                link.click();
                link.remove();
            }
            window.setTimeout(() => URL.revokeObjectURL(pdfUrl), 120000);
        } catch (error) {
            console.error("Could not generate report PDF:", error);
            if (pdfWindow && !pdfWindow.closed) pdfWindow.close();
            alert("Something went wrong generating the PDF. Please try again.");
        } finally {
            downloadBtn.disabled = false;
            downloadBtn.innerHTML = originalIcon;
        }
    }
})();