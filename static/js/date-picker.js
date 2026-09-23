(function () {
    // Attaches a small calendar dropdown to any input with the "date-picker"
    // class. Values are read/written as "DD-MM-YYYY" text, matching the date
    // format used everywhere else in this app (assessment dates, attendance
    // dates, etc.) — unlike a native <input type="date">, which stores
    // "YYYY-MM-DD" and would be inconsistent with that.

    const MONTH_NAMES = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ];

    function pad(n) {
        return String(n).padStart(2, "0");
    }

    function formatDMY(date) {
        return `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()}`;
    }

    function parseDMY(value) {
        const match = /^(\d{2})-(\d{2})-(\d{4})$/.exec(String(value || "").trim());
        if (!match) return null;
        const day = Number(match[1]);
        const month = Number(match[2]) - 1;
        const year = Number(match[3]);
        const parsed = new Date(year, month, day);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function isSameDay(a, b) {
        return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }

    function closeAllPanels() {
        document.querySelectorAll(".date-picker-panel.open").forEach((panel) => panel.classList.remove("open"));
    }

    function renderPanel(panel, input, viewYear, viewMonth) {
        const today = new Date();
        const selected = parseDMY(input.value);
        const firstDay = new Date(viewYear, viewMonth, 1);
        const startWeekday = firstDay.getDay();
        const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
        const daysInPrevMonth = new Date(viewYear, viewMonth, 0).getDate();

        let daysHtml = "";
        for (let i = startWeekday - 1; i >= 0; i--) {
            daysHtml += `<span class="date-picker-day faded">${daysInPrevMonth - i}</span>`;
        }
        for (let d = 1; d <= daysInMonth; d++) {
            const cellDate = new Date(viewYear, viewMonth, d);
            const classes = ["date-picker-day"];
            if (isSameDay(cellDate, today)) classes.push("date-picker-today");
            if (selected && isSameDay(cellDate, selected)) classes.push("date-picker-selected");
            daysHtml += `<span class="${classes.join(" ")}" data-day="${d}">${d}</span>`;
        }
        const trailing = (7 - ((startWeekday + daysInMonth) % 7)) % 7;
        for (let d = 1; d <= trailing; d++) {
            daysHtml += `<span class="date-picker-day faded">${d}</span>`;
        }

        panel.innerHTML = `
            <div class="date-picker-header">
                <button type="button" class="date-picker-nav" data-nav="-1" aria-label="Previous month"><i class="ti ti-chevron-left"></i></button>
                <span class="date-picker-label">${MONTH_NAMES[viewMonth]} ${viewYear}</span>
                <button type="button" class="date-picker-nav" data-nav="1" aria-label="Next month"><i class="ti ti-chevron-right"></i></button>
            </div>
            <div class="date-picker-weekdays">
                <span>S</span><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span>
            </div>
            <div class="date-picker-days">${daysHtml}</div>
            <div class="date-picker-footer">
                <button type="button" class="date-picker-today-btn" data-today="1">Today</button>
            </div>
        `;

        panel.querySelectorAll("[data-nav]").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.stopPropagation();
                let newMonth = viewMonth + parseInt(button.dataset.nav, 10);
                let newYear = viewYear;
                if (newMonth < 0) { newMonth = 11; newYear -= 1; }
                if (newMonth > 11) { newMonth = 0; newYear += 1; }
                renderPanel(panel, input, newYear, newMonth);
            });
        });

        panel.querySelectorAll("[data-day]").forEach((cell) => {
            cell.addEventListener("click", (event) => {
                event.stopPropagation();
                const picked = new Date(viewYear, viewMonth, parseInt(cell.dataset.day, 10));
                input.value = formatDMY(picked);
                input.dispatchEvent(new Event("change", { bubbles: true }));
                panel.classList.remove("open");
            });
        });

        const todayButton = panel.querySelector("[data-today]");
        todayButton.addEventListener("click", (event) => {
            event.stopPropagation();
            input.value = formatDMY(new Date());
            input.dispatchEvent(new Event("change", { bubbles: true }));
            panel.classList.remove("open");
        });
    }

    function attach(input) {
        if (input.dataset.datePickerAttached) return;
        input.dataset.datePickerAttached = "1";
        input.setAttribute("readonly", "readonly");
        input.setAttribute("autocomplete", "off");
        input.classList.add("date-picker-input");
        if (!input.placeholder) input.placeholder = "DD-MM-YYYY";

        const wrap = document.createElement("div");
        wrap.className = "date-picker-wrap";
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        const icon = document.createElement("i");
        icon.className = "ti ti-calendar date-picker-icon";
        wrap.appendChild(icon);

        const panel = document.createElement("div");
        panel.className = "date-picker-panel";
        wrap.appendChild(panel);

        function open() {
            const wasOpen = panel.classList.contains("open");
            closeAllPanels();
            if (wasOpen) return;
            const base = parseDMY(input.value) || new Date();
            renderPanel(panel, input, base.getFullYear(), base.getMonth());
            panel.classList.add("open");
        }

        input.addEventListener("click", (event) => {
            event.stopPropagation();
            open();
        });
        icon.addEventListener("click", (event) => {
            event.stopPropagation();
            open();
        });
        panel.addEventListener("click", (event) => event.stopPropagation());
    }

    function attachAll() {
        document.querySelectorAll(".date-picker").forEach(attach);
    }

    document.addEventListener("DOMContentLoaded", attachAll);
    document.addEventListener("click", closeAllPanels);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeAllPanels();
    });

    // In case a template ever injects date-picker inputs after page load.
    window.initDatePickers = attachAll;
})();