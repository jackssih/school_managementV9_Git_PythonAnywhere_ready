(function () {
    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function setValue(id, value) {
        const element = document.getElementById(id);
        if (element) element.value = value || "";
    }

    function parseRecord(button) {
        try {
            return JSON.parse(button.dataset.record || "{}");
        } catch (error) {
            console.error("Could not read grade action data:", error);
            return {};
        }
    }

    function aggregateFromMark(value) {
        const score = Number.parseInt(value, 10);
        if (Number.isNaN(score)) return "";
        if (score >= 90) return "1";
        if (score >= 80) return "2";
        if (score >= 70) return "3";
        if (score >= 60) return "4";
        if (score >= 55) return "5";
        if (score >= 50) return "6";
        if (score >= 45) return "7";
        if (score >= 40) return "8";
        return "9";
    }

    function setAssessmentSubject(record) {
        const select = document.getElementById("assessment-edit-subject");
        if (!select) return;
        const match = Array.from(select.options).find((option) => {
            return option.dataset.subjectName === record.subject && option.dataset.className === record.class_name;
        });
        if (match) select.value = match.value;
    }

    window.openAssessmentEdit = function (record) {
        document.getElementById("assessmentEditForm").action = `${ASSESSMENT_URL_BASE}/${record.id}/edit`;
        setValue("assessment-edit-date", record.date);
        setAssessmentSubject(record);
        setValue("assessment-edit-type", record.assessment_type);
        setValue("assessment-edit-maximum", record.maximum);
        openModal("assessmentEditModal");
    };

    window.openResultsModal = function (record) {
        document.getElementById("resultsModalTitle").textContent =
            `${record.subject} results · ${record.recorded_label}`;
        document.getElementById("resultsForm").action = `${ASSESSMENT_URL_BASE}/${record.id}/results`;

        const students = record.students || [];
        const isLetterGrade = record.result_mode === "letter";
        document.getElementById("resultsGrid").innerHTML = students.length
            ? `
                <div class="result-row result-row-header ${isLetterGrade ? "result-row-letter" : ""}">
                    <span>Name</span>
                    ${isLetterGrade ? "<span>Grade</span><span>Teacher's assessment</span>" : "<span>Score</span><span>Aggregate</span>"}
                </div>
                ${students.map((student) => {
                    if (isLetterGrade) {
                        const grade = String(student.grade || "").toUpperCase();
                        return `
                            <div class="result-row result-row-letter">
                                <div>
                                    <p class="promotion-name">${escapeHtml(student.name)}</p>
                                </div>
                                <select class="form-input" name="grade_${student.id}">
                                    <option value="">Choose</option>
                                    ${["A", "B", "C", "D", "E", "F"].map((option) => (
                                        `<option value="${option}" ${grade === option ? "selected" : ""}>${option}</option>`
                                    )).join("")}
                                </select>
                                <input class="form-input" type="text" name="remark_${student.id}"
                                       value="${escapeHtml(student.remark || "")}" placeholder="e.g. Good grasp, needs more practice">
                            </div>
                        `;
                    }

                    return `
                        <div class="result-row">
                            <div>
                                <p class="promotion-name">${escapeHtml(student.name)}</p>
                            </div>
                            <input class="form-input result-mark-input" type="number" min="0" max="${record.maximum || 100}"
                                   name="mark_${student.id}" value="${escapeHtml(student.mark || "")}" placeholder="0-${record.maximum || 100}">
                            <input class="form-input result-aggregate-input" type="text"
                                   name="aggregate_${student.id}" value="${escapeHtml(student.aggregate || "")}" placeholder="Agg">
                        </div>
                    `;
                }).join("")}
            `
            : '<p class="form-subheading">No students are enrolled in this class yet.</p>';

        document.querySelectorAll(".result-mark-input").forEach((input) => {
            input.addEventListener("input", () => {
                const aggregateInput = input.closest(".result-row").querySelector(".result-aggregate-input");
                if (aggregateInput) aggregateInput.value = aggregateFromMark(input.value);
            });
        });

        openModal("resultsModal");
    };

    window.openCommentEdit = function (record) {
        document.getElementById("commentEditForm").action = `${COMMENT_URL_BASE}/${record.id}/edit`;
        setValue("comment-edit-student", record.student_id);
        setValue("comment-edit-type", record.comment_type);
        setValue("comment-edit-report-stage", record.report_stage);
        setValue("comment-edit-teacher", record.teacher);
        setValue("comment-edit-text", record.comment);
        openModal("commentEditModal");
    };

    // Keeps the Teacher dropdown in sync with the chosen "Comment by" role —
    // the dropdown only ever holds this class's class teacher and the
    // school's head teacher, so picking the role can safely pick the person too.
    function syncCommentTeacher(typeSelectId, teacherSelectId) {
        const typeSelect = document.getElementById(typeSelectId);
        const teacherSelect = document.getElementById(teacherSelectId);
        if (!typeSelect || !teacherSelect) return;
        typeSelect.addEventListener("change", () => {
            const match = Array.from(teacherSelect.options).find((option) => option.dataset.role === typeSelect.value);
            if (match) teacherSelect.value = match.value;
        });
    }
    syncCommentTeacher("comment-type", "comment-teacher");
    syncCommentTeacher("comment-edit-type", "comment-edit-teacher");

    window.openDeleteConfirm = function (formId, label) {
        document.getElementById("confirmDeleteText").textContent =
            `This will permanently remove ${label}. This can't be undone.`;
        const button = document.getElementById("confirmDeleteBtn");
        button.onclick = function () {
            document.getElementById(formId).submit();
        };
        openModal("confirmDeleteModal");
    };

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-grade-action]");
        if (!button) return;

        const action = button.dataset.gradeAction;
        if (action === "results") {
            openResultsModal(parseRecord(button));
        } else if (action === "edit-assessment") {
            openAssessmentEdit(parseRecord(button));
        } else if (action === "edit-comment") {
            openCommentEdit(parseRecord(button));
        } else if (action === "delete") {
            openDeleteConfirm(button.dataset.formId, button.dataset.label || "this record");
        }
    });
})();