// The sticky navbar's height as --navbar-height on the page, for what sticks
// below it: themes give the navbar different heights, and a phone's menu opens it.
(function () {
    var navbar = document.querySelector(".navbar.sticky-top");
    if (!navbar) return;
    function measure() {
        document.documentElement.style.setProperty("--navbar-height", navbar.offsetHeight + "px");
    }
    measure();
    if (window.ResizeObserver) new ResizeObserver(measure).observe(navbar);
})();
