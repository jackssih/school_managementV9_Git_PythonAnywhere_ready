(function () {
    const monthNames = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ];

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function renderCalendar(container, year, month) {
        const today = new Date();
        const schoolEvents = window.SCHOOL_EVENTS || [];
        const isCurrentMonth = today.getFullYear() === year && today.getMonth() === month;
        const firstDay = new Date(year, month, 1);
        const startWeekday = firstDay.getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const daysInPrevMonth = new Date(year, month, 0).getDate();

        let html = `
            <div class="calendar-header">
                <i class="ti ti-chevron-left" data-nav="-1"></i>
                <p class="calendar-month-label">${monthNames[month]} ${year}</p>
                <i class="ti ti-chevron-right" data-nav="1"></i>
            </div>
            <div class="calendar-weekdays">
                <span>S</span><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span>
            </div>
            <div class="calendar-days">
        `;

        for (let i = startWeekday - 1; i >= 0; i--) {
            html += `<span class="cal-day faded">${daysInPrevMonth - i}</span>`;
        }

        for (let d = 1; d <= daysInMonth; d++) {
            const isToday = isCurrentMonth && d === today.getDate();
            const dateKey = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
            const dayEvents = schoolEvents.filter((event) => {
                if (!event.start) return false;
                const end = event.end || event.start;
                return event.start <= dateKey && dateKey <= end;
            });
            const eventClass = dayEvents.length ? "cal-event" : "";
            const title = escapeHtml(dayEvents.map((event) => event.title).join(", "));
            html += `<span class="cal-day ${isToday ? "cal-today" : ""} ${eventClass}" title="${title}">${d}</span>`;
        }

        const totalCells = startWeekday + daysInMonth;
        const trailing = (7 - (totalCells % 7)) % 7;
        for (let d = 1; d <= trailing; d++) {
            html += `<span class="cal-day faded">${d}</span>`;
        }

        html += `</div>`;
        container.innerHTML = html;

        container.querySelectorAll("[data-nav]").forEach((el) => {
            el.addEventListener("click", () => {
                const delta = parseInt(el.getAttribute("data-nav"), 10);
                let newMonth = month + delta;
                let newYear = year;
                if (newMonth < 0) { newMonth = 11; newYear -= 1; }
                if (newMonth > 11) { newMonth = 0; newYear += 1; }
                renderCalendar(container, newYear, newMonth);
            });
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        const container = document.getElementById("calendarCard");
        if (!container) return;
        const now = new Date();
        renderCalendar(container, now.getFullYear(), now.getMonth());
    });
})();
