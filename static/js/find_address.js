// The Instances page's "Find by address" dialog: the running VMs that use an
// IP address or an address in a network (instances.views.find_address), with
// where each address came from and what the search could not check.
(function () {
    var dialog = document.getElementById("find-address");
    var form = document.getElementById("find-address-form");
    var error = document.getElementById("find-address-error");
    var table = document.getElementById("find-address-results");
    var coverage = document.getElementById("find-address-coverage");
    var button = form.querySelector("button[type=submit]");
    var text = dialog.dataset;

    function cell(row, content) {
        var td = document.createElement("td");
        if (content instanceof Node) {
            td.appendChild(content);
        } else {
            td.textContent = content;
        }
        row.appendChild(td);
        return td;
    }

    function vmCell(match) {
        if (match.url) {
            var link = document.createElement("a");
            link.href = match.url;
            link.textContent = match.vm;
            return link;
        }
        return document.createTextNode(match.vm + " " + text.unregistered);
    }

    function coverageText(c) {
        var lines = [text.checked.replace("%(n)s", c.checked)];
        if (c.no_agent) {
            lines.push(text.noAgent.replace("%(n)s", c.no_agent));
        }
        if (c.unread) {
            lines.push(text.unread.replace("%(n)s", c.unread));
        }
        if (c.hosts_down && c.hosts_down.length) {
            lines.push(text.hostsDown.replace("%(hosts)s", c.hosts_down.join(", ")));
        }
        if (c.hosts_unfinished && c.hosts_unfinished.length) {
            lines.push(text.hostsUnfinished.replace("%(hosts)s", c.hosts_unfinished.join(", ")));
        }
        if (c.some_unchecked) {
            lines.push(text.someUnchecked);
        }
        return lines.join(" ");
    }

    function show(answer) {
        error.textContent = answer.error || "";
        error.classList.toggle("d-none", !answer.error);
        var body = table.tBodies[0];
        body.replaceChildren();
        var matches = answer.matches || [];
        matches.forEach(function (match) {
            var row = body.insertRow();
            var address = cell(row, match.address);
            if (match.conflict) {
                var badge = document.createElement("span");
                badge.className = "badge bg-warning-subtle text-warning-emphasis ms-1";
                badge.textContent = text.conflict;
                address.appendChild(badge);
            }
            cell(row, vmCell(match));
            cell(row, match.mac);
            cell(row, match.sources.join(", "));
            if ("host" in match) {
                cell(row, match.host);
            }
        });
        table.classList.toggle("d-none", matches.length === 0);
        if (answer.coverage) {
            var readAt = text.readAt.replace("%(time)s", new Date(answer.read_at).toLocaleTimeString());
            coverage.textContent = (matches.length ? "" : text.none + " ") + coverageText(answer.coverage) + " " + readAt;
        } else {
            coverage.textContent = "";
        }
    }

    // an address typed in the list's search box is what the dialog looks for
    dialog.addEventListener("show.bs.modal", function () {
        var typed = document.getElementById("filter").value.trim();
        if (/^[0-9a-fA-F:.]+(\/[0-9]+)?$/.test(typed) && /[.:]/.test(typed)) {
            form.elements.q.value = typed;
        }
    });
    dialog.addEventListener("shown.bs.modal", function () {
        form.elements.q.focus();
    });

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        button.disabled = true;
        var url = text.url + "?" + new URLSearchParams({q: form.elements.q.value});
        fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}}).then(function (response) {
            return response.json();
        }).catch(function () {
            return {error: text.failed};
        }).then(function (answer) {
            show(answer);
            button.disabled = false;
        });
    });
})();
