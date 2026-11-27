(function() {
        const academicsConfig = document.getElementById("academics-config");
        const CLASS_EDIT_URL_BASE = academicsConfig?.dataset.classEditUrlBase || "/academics/classes";
        const SUBJECT_EDIT_URL_BASE = academicsConfig?.dataset.subjectEditUrlBase || "/academics/subjects";
        const ENROLLMENT_EDIT_URL_BASE = academicsConfig?.dataset.enrollmentEditUrlBase || "/academics/enrollment";
        const PROMOTION_URL_BASE = academicsConfig?.dataset.promotionUrlBase || "/academics/promotion";
        const PROMOTION_RECORDS = academicsConfig?.dataset.promotionRecords ? JSON.parse(academicsConfig.dataset.promotionRecords) : [];
        const PROMOTION_ACTIONS = academicsConfig?.dataset.promotionActions ? JSON.parse(academicsConfig.dataset.promotionActions) : [];
        const MANUAL_RECORDS = academicsConfig?.dataset.promotionManualRecords ? JSON.parse(academicsConfig.dataset.promotionManualRecords) : [];
        const MANUAL_TARGETS = academicsConfig?.dataset.promotionManualTargets ? JSON.parse(academicsConfig.dataset.promotionManualTargets) : [];
        const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
        function setValue(id, value) {
            const element = document.getElementById(id);
            if (element) element.value = value || "";
        }

        function setChecked(id, value) {
            const element = document.getElementById(id);
            if (element) element.checked = Boolean(value);
        }

        function setSelectedValues(id, values) {
            const element = document.getElementById(id);
            if (!element) return;
            const selected = new Set((values || []).map(String));
            Array.from(element.options).forEach((option) => {
                option.selected = selected.has(option.value);
            });
        }

        function detailRows(rows) {
            return rows.map(([label, value]) => `
            <div class="view-row">
                <span class="view-label">${label}</span>
                <span>${value || "—"}</span>
            </div>
        `).join("");
        }

        function openDetails(title, rows) {
            document.getElementById("viewModalTitle").textContent = title;
            document.getElementById("viewModalBody").innerHTML = detailRows(rows);
            openModal("viewModal");
        }

        window.openClassView = function(record) {
            openDetails(record.name, [
                ["Name", record.name],
                ["Curriculum", record.curriculum],
                ["Enrolled students", record.enrolled_students],
                ["Subjects", record.subject_names && record.subject_names.length ? record.subject_names.join(", ") : "—"],
                ["Teacher", record.teacher],
            ]);
        };

        window.openClassEdit = function(record) {
            document.getElementById("classEditForm").action = `${CLASS_EDIT_URL_BASE}/${record.id}/edit`;
            setValue("class-edit-name", record.name);
            setValue("class-edit-curriculum", record.curriculum || "Standard");
            setValue("class-edit-teacher", record.teacher);
            openModal("classEditModal");
        };

        window.openSubjectView = function(record) {
            openDetails(record.name, [
                ["Subject", record.name],
                ["Class", record.class_name],
                ["Maximum mark", record.maximum_mark],
                ["Subject type", record.subject_type_label],
                ["Teacher", record.teacher],
                ["Students", record.students_count],
            ]);
        };

        window.openSubjectEdit = function(record) {
            document.getElementById("subjectEditForm").action = `${SUBJECT_EDIT_URL_BASE}/${record.id}/edit`;
            setValue("subject-edit-name", record.name);
            setValue("subject-edit-class", record.class_name);
            setValue("subject-edit-mark", record.maximum_mark);
            setChecked("subject-edit-compulsory", record.is_compulsory);
            setValue("subject-edit-teacher", record.teacher);
            openModal("subjectEditModal");
        };

        window.openEnrollmentView = function(record) {
            openDetails(record.description, [
                ["Date", record.date],
                ["Class", record.class_name],
                ["Students", record.students && record.students.length ? record.students.join(", ") : "—"],
                ["Status", record.status],
            ]);
        };

        window.openEnrollmentEdit = function(record) {
            document.getElementById("enrollmentEditForm").action = `${ENROLLMENT_EDIT_URL_BASE}/${record.id}/edit`;
            setValue("enrollment-edit-class", record.class_name);
            setSelectedValues("enrollment-edit-students", record.student_ids);
            setValue("enrollment-edit-status", record.status);
            openModal("enrollmentEditModal");
        };

        window.openStudentList = function(title, students) {
            document.getElementById("listModalTitle").textContent = title;
            const rows = (students || []).map((student) => [
                student.name,
                student.class_name || "—",
            ]);
            document.getElementById("listModalBody").innerHTML = rows.length ?
                detailRows(rows) :
                '<p class="form-subheading">No students found.</p>';
            openModal("listModal");
        };

        window.openNameList = function(title, names) {
            document.getElementById("listModalTitle").textContent = title;
            document.getElementById("listModalBody").innerHTML = names && names.length ?
                names.map((name) => `<div class="view-row"><span>${name}</span></div>`).join("") :
                '<p class="form-subheading">No students found.</p>';
            openModal("listModal");
        };

        window.openPromotionModal = function(record) {
                document.getElementById("promotionModalTitle").textContent = `${record.class_name} promotion`;
                document.getElementById("promotionForm").action = `${PROMOTION_URL_BASE}/${record.id}/decisions`;
                document.getElementById("bulk-action").value = "";
                document.getElementById("promotionStudents").innerHTML = (record.students || []).length ?
                    record.students.map((student) => `
                <div class="promotion-row">
                    <div>
                        <p class="promotion-name">${student.name}</p>
                    </div>
                    <select class="form-input" name="student_${student.id}">
                        <option value="">No action</option>
                        ${PROMOTION_ACTIONS.map((action) => `<option value="${action}">${action}</option>`).join("")}
                    </select>
                </div>
            `).join("")
            : '<p class="form-subheading">No students are linked to this class yet.</p>';
        openModal("promotionModal");
    };

    // Manual promotion: choose a class, tick students, pick the class to move them into.
    window.openManualPromotion = function () {
        const from = document.getElementById("manualFromClass");
        const target = document.getElementById("manualTargetClass");
        const list = document.getElementById("manualStudents");
        const selectAll = document.getElementById("manualSelectAll");
        if (!from || !target || !list) return;

        const optionsFor = (curriculum) => MANUAL_TARGETS.filter((t) => t.curriculum === curriculum)
            .map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join("");
        const groups = [["Nursery & Primary classes", "Standard"], ["ACE grades", "ACE"]];
        target.innerHTML = groups.map(([label, key]) => {
            const html = optionsFor(key);
            return html ? `<optgroup label="${label}">${html}</optgroup>` : "";
        }).join("");

        from.innerHTML = MANUAL_RECORDS.map((r) =>
            `<option value="${r.id}">${escapeHtml(r.class_name)} (${(r.students || []).length})</option>`).join("");

        const renderStudents = () => {
            const record = MANUAL_RECORDS.find((r) => String(r.id) === from.value);
            const students = (record && record.students) || [];
            selectAll.checked = false;
            list.innerHTML = students.length ? students.map((s) => `
                <label style="display:flex;gap:8px;align-items:center;padding:4px 0;cursor:pointer;">
                    <input type="checkbox" name="student_ids" value="${s.id}"> ${escapeHtml(s.name)}
                </label>`).join("") : '<p class="form-subheading">No students are enrolled in this class.</p>';
            if (record && record.next_class_id) target.value = String(record.next_class_id);
        };
        from.onchange = renderStudents;
        selectAll.onchange = () => list.querySelectorAll('input[name="student_ids"]').forEach((box) => { box.checked = selectAll.checked; });
        renderStudents();
        openModal("promotionManualModal");
    };

    window.openPickedPromotion = function () {
        const picker = document.getElementById("promotion-class-picker");
        const record = (PROMOTION_RECORDS || []).find((item) => String(item.id) === picker.value);
        if (!record) return;
        closeModal("promotionAddModal");
        openPromotionModal(record);
    };


        window.openEnrollmentStudentView = function(record, className) {
            openDetails(record.name, [
                ["Student ID", record.registration_number],
                ["Class", className],
                ["Gender", record.gender || "—"],
                ["Status", record.status],
                ["Date enrolled", record.enrollment_date],
            ]);
        };
    window.openDeleteConfirm = function (formId, label) {
        document.getElementById("confirmDeleteText").textContent =
            `This will update or remove ${label}. Continue?`;
        document.getElementById("confirmDeleteBtn").onclick = function () {
            document.getElementById(formId).submit();
        };
        openModal("confirmDeleteModal");
    };
})();