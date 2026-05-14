document.addEventListener("DOMContentLoaded", () => {
    document.body.classList.add("loaded");
});

document.querySelectorAll("a").forEach(link => {
    link.addEventListener("click", e => {
        if (link.getAttribute("href").startsWith("/")) {
            document.body.style.opacity = "0";
        }
    });
});
