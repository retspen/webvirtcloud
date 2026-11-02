// Starts the job panel of a resource page from its settings (job_panel_script tag).
(function () {
    var settings = JSON.parse(document.getElementById("job-panel-settings").textContent);
    window.resourceJobPanel = jobPanel(document.getElementById("job-panel"), {
        resource: settings.resource,
        job: function (id) { return settings.jobs + id + "/"; },
        cancel: function (id) { return settings.jobs + id + "/cancel/"; },
    }, settings.csrf_token, settings.remembered, settings.states, settings.text);
})();
