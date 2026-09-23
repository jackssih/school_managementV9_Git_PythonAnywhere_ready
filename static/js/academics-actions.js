(function() {
        const academicsConfig = document.getElementById("academics-config");
        const CLASS_EDIT_URL_BASE = academicsConfig?.dataset.classEditUrlBase || "/academics/classes";
        const SUBJECT_EDIT_URL_BASE = academicsConfig?.dataset.subjectEditUrlBase || "/academics/subjects";
        const ENROLLMENT_EDIT_URL_BASE = academicsConfig?.dataset.enrollmentEditUrlBase || "/academics/enrollment";
        const PROMOTION_URL_BASE = academicsConfig?.dataset.promotionUrlBase || "/academics/promotion";
        const PROMOTION_RECORDS = academicsConfig?.dataset.promotionRecords ? JSON.parse(academicsConfig.dataset.promotionRecords) : [];
        const PROMOTION_ACTIONS = academicsConfig?.dataset.promotionActions ? JSON.parse(academicsConfig.dataset.promotionActions) : [];
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
                ["Enrolled students", record.enrolled_students],
                ["Subjects", record.subject_names && record.subject_names.length ? record.subject_names.join(", ") : "—"],
                ["Teacher", record.teacher],
            ]);
        };

        window.openClassEdit = function(record) {
            document.getElementById("classEditForm").action = `${CLASS_EDIT_URL_BASE}/${record.id}/edit`;
            setValue("class-edit-name", record.name);
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