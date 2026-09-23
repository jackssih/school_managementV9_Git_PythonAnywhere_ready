(function () {
    document.addEventListener("DOMContentLoaded", () => {
        const badge = document.getElementById("profileBadge");
        const menu = document.getElementById("profileMenu");
        if (!badge || !menu) return;

        badge.addEventListener("click", (e) => {
            e.stopPropagation();
            menu.classList.toggle("open");
        });

        document.addEventListener("click", () => {
            menu.classList.remove("open");
        });
    });
})();
