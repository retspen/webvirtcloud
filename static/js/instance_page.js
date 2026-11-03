// The VM page (instance.html and its tabs). Page-wide values are data
// attributes of #vm-summary; the others are on the element they belong to.
(function () {
    var summary = document.getElementById("vm-summary");

    // Open the tab whose control targets "#<pane id>"
    function show_tab(target) {
        var controls = document.querySelectorAll('[data-bs-target], a[data-bs-toggle][href]');
        for (var i = 0; i < controls.length; i++) {
            var c = controls[i];
            if ((c.getAttribute('data-bs-target') || c.getAttribute('href')) === target) {
                bootstrap.Tab.getOrCreateInstance(c).show();
                return;
            }
        }
    }

    function on(id, event, handler) {
        var element = document.getElementById(id);
        if (element) element.addEventListener(event, handler);
    }

    // the guest OS details, read through the guest agent
    function load_osinfo() {
        var error = $('#osinfo-error');
        var silent = error[0].dataset.silent;
        $.getJSON(summary.dataset.osinfoUrl, function (data) {
            error.addClass('d-none');
            $('#oshostname').text(data['host-name'] || '');
            $('#osname').text(data.id || '');
            $('#osprettyname').text(data['pretty-name'] || '');
            $('#oskernelrelease').text(data['kernel-release'] || '');
            $('#oskernelversion').text(data['kernel-version'] || '');
            $('#osversion').text(data.version || '');
            $('#ostimezone').text(data.zone ? data.zone + " / " + data.offset : '');
        }).fail(function (xhr) {
            var message = xhr.responseJSON && xhr.responseJSON.error;
            error.text(message || silent).removeClass('d-none');
        });
    }
    function get_osinfo() {
        show_tab('#settings');
        show_tab('#osinfo');
        load_osinfo();
    }
    on("os-details-button", "click", get_osinfo);
    on("osinfo-tab", "click", get_osinfo);
    on("clone-button", "click", function () {
        show_tab('#settings');
        show_tab('#clone');
    });

    if (summary.dataset.vdiUrl) {
        $.get(summary.dataset.vdiUrl, function (data) {
            $("#vdi_url_input").attr("value", data);
            $("#vdi_url").attr("href", data);
        });
    }

    // a switch whose form is sent as soon as it is flipped
    document.querySelectorAll("[data-submit-on-change]").forEach(function (input) {
        input.addEventListener("change", function () { input.form.submit(); });
    });

    // a memory snapshot freezes the guest by itself: the freeze option waits
    // until memory is unchecked, then is what it was
    on("snapshot-memory", "change", function () {
        var quiesce = document.getElementById('snapshot-quiesce');
        if (!quiesce.dataset.offered) return;
        if (this.checked) quiesce.dataset.was = quiesce.checked;
        quiesce.disabled = this.checked;
        quiesce.checked = !this.checked && quiesce.dataset.was !== 'false';
    });

    // the Add disk dialog: the form goes where the chosen source is made,
    // and an existing volume is chosen from the volumes of its pool
    var addvol = document.getElementById('addvol');
    if (addvol) {
        var addvolForm = document.getElementById('addvol-form');
        choiceDialog(addvol, 'disk_source', function (source) {
            addvolForm.action = addvolForm.dataset[source];
        });
    }
    var pool = document.getElementById("selected_storage");
    if (pool) {
        pool.addEventListener("change", function () {
            $.getJSON(pool.dataset.volumesUrl.replace("__pool__", encodeURIComponent(pool.value)), function (data) {
                var vols = $("#vols").empty();
                $.each(data['vols'], function (i, item) {
                    vols.append($("<option>").val(item).text(item));
                });
            });
        });
    }

    // MAC addresses and names of a clone or a new NIC
    function random_mac(name) {
        $.getJSON(summary.dataset.randomMacUrl, function (data) {
            $('input[name="' + name + '"]').val(data['mac']);
        });
    }
    document.querySelectorAll("[data-random-mac]").forEach(function (button) {
        button.addEventListener("click", function () { random_mac(button.dataset.randomMac); });
    });
    var cloneName = document.getElementById("clone_name");
    // the DHCP host entry of the clone's name holds one address: the first NIC's
    function guess_mac_address() {
        $.getJSON(cloneName.dataset.guessMacUrl.replace("__name__", encodeURIComponent(cloneName.value)), function (data) {
            $('input[name="clone-net-mac-0"]').val(data['mac']);
        });
    }
    // each disk of the clone is named after the clone
    function update_clone_disk_name(new_vname) {
        var vname = cloneName.dataset.source;
        document.querySelectorAll("input[data-image]").forEach(function (input) {
            var disk_name = input.dataset.image;
            var disk_dot = disk_name.split('.');
            var disk_dot_suffix = disk_dot[disk_dot.length - 1];
            var image;
            if (disk_name.startsWith(vname)) {
                image = disk_name.replace(vname, new_vname);
            } else if (disk_name.lastIndexOf('.') > -1 && disk_dot_suffix.length <= 7) {
                disk_dot.pop();
                image = new_vname + "-" + disk_dot.join('-') + "." + disk_dot_suffix;
            } else if (new_vname != disk_name) {
                image = new_vname;
            } else {
                image = new_vname + '-clone';
            }
            input.value = image;
        });
    }
    function guess_clone_name() {
        var help = $('#clone-name-help');
        var noName = help[0].dataset.noName;
        $.getJSON(cloneName.dataset.guessUrl, function (data) {
            // a free name of the DHCP file, if there is one
            if (!data.name) {
                help.text(noName);
                return;
            }
            help.text('');
            cloneName.value = data['name'].split(".")[0];
            update_clone_disk_name(cloneName.value);
            guess_mac_address();
        });
    }
    if (cloneName) {
        cloneName.addEventListener("input", function () { update_clone_disk_name(cloneName.value); });
        on("guess-clone-name", "click", guess_clone_name);
        on("guess-clone-mac", "click", guess_mac_address);
        update_clone_disk_name(cloneName.value);
    }
    // every NIC of the clone a new address: one the VM has would clash with it
    document.querySelectorAll("[data-new-mac]").forEach(function (input) { random_mac(input.name); });

    // the boot order: the devices of #boot-chain in turn, as "disk:vda,cdrom:sda"; each moves on its own
    var chain = document.getElementById("boot-chain");
    if (chain) {
        var spare = document.getElementById("boot-spare");
        var refresh = function () {
            var nodes = Array.from(chain.children);
            document.getElementById("bootorder").value = nodes.map(function (node) { return node.dataset.bootValue; }).join(",");
            document.getElementById("boot-chain-empty").hidden = nodes.length > 0;
            nodes.forEach(function (node, i) {
                node.querySelector('[data-boot="up"]').disabled = i === 0;
                node.querySelector('[data-boot="down"]').disabled = i === nodes.length - 1;
            });
        };
        document.getElementById("boot_opt").addEventListener("click", function (event) {
            var button = event.target.closest("[data-boot]");
            if (!button) return;
            var node = button.closest(".boot-node");
            var action = button.dataset.boot;
            if (action === "up") chain.insertBefore(node, node.previousElementSibling);
            if (action === "down") chain.insertBefore(node.nextElementSibling, node);
            if (action === "remove") spare.prepend(node);
            if (action === "add") chain.append(node);
            refresh();
            // the keyboard stays on the device that moved
            var same = { up: "up", down: "down", remove: "add", add: "remove" }[action];
            var target = node.querySelector('[data-boot="' + same + '"]');
            if (target.disabled) target = node.querySelector('.boot-chain-only [data-boot]:not([disabled])');
            target.focus();
        });
        refresh();
    }

    // the Host devices tab's add forms: loaded once, when the tab first opens
    var hostDevices = document.getElementById("host-devices");
    if (hostDevices) {
        document.querySelector('[data-bs-target="#hostdevs"]').addEventListener("shown.bs.tab", function () {
            if (hostDevices.dataset.loaded) return;
            hostDevices.dataset.loaded = "true";
            fetch(hostDevices.dataset.url).then(function (response) {
                if (!response.ok) throw new Error(response.statusText);
                return response.text();
            }).then(function (html) {
                hostDevices.innerHTML = html;
            }).catch(function () {
                hostDevices.textContent = hostDevices.dataset.failed;
            });
        });
    }

    // the Migrate tab's disks: loaded for the chosen destination when the tab opens or the choice changes
    // the form is not sent until the disks of the chosen destination are shown
    var migratePlan = document.getElementById("migrate-plan");
    var migrateCompute = document.getElementById("migrate_compute");
    var migrateLoading = null;
    function loadMigratePlan() {
        if (!migrateCompute.value) return;
        if (migrateLoading) migrateLoading.abort();
        var loading = migrateLoading = new AbortController();
        var submit = migratePlan.closest("form").querySelector('button[name="migrate"]');
        submit.disabled = true;
        migratePlan.textContent = migratePlan.dataset.checkingDisks;
        fetch(migratePlan.dataset.url + "?compute_id=" + encodeURIComponent(migrateCompute.value),
              {signal: loading.signal}).then(function (response) {
            if (!response.ok) throw new Error(response.statusText);
            return response.text();
        }).then(function (html) {
            migratePlan.innerHTML = html;
            // a destination that did not answer, or a disk that cannot go there
            submit.disabled = migratePlan.querySelector("[data-refused]") !== null;
        }).catch(function () {
            if (loading.signal.aborted) return;  // another destination was chosen
            migratePlan.textContent = migratePlan.dataset.disksFailed;
            submit.disabled = false;  // the migration checks them again
        });
    }
    // the destinations that cannot be chosen (unreachable, or this host under
    // another record) are marked first; then the disks of the first one left
    function loadMigrateTargets() {
        var submit = migratePlan.closest("form").querySelector('button[name="migrate"]');
        submit.disabled = true;
        migrateCompute.disabled = true;  // no disks are checked for a host before the hosts are
        migratePlan.textContent = migratePlan.dataset.checkingHosts;
        fetch(migratePlan.dataset.targetsUrl).then(function (response) {
            if (!response.ok) throw new Error(response.statusText);
            return response.json();
        }).then(function (refused) {
            migrateCompute.disabled = false;
            Array.prototype.forEach.call(migrateCompute.options, function (option) {
                if (refused[option.value]) {
                    option.disabled = true;
                    option.textContent = refused[option.value];  // it names the host
                }
            });
            var first = Array.prototype.find.call(migrateCompute.options, function (option) { return !option.disabled; });
            if (!first) {
                migratePlan.textContent = migratePlan.dataset.noHost;
                return;
            }
            if (migrateCompute.selectedOptions[0].disabled) migrateCompute.value = first.value;
            loadMigratePlan();
        }).catch(function () {
            migratePlan.textContent = migratePlan.dataset.hostsFailed;
        });
    }
    if (migratePlan && migrateCompute) {
        document.querySelector('[data-bs-target="#migrate"]').addEventListener("shown.bs.tab", function () {
            if (!migratePlan.dataset.loaded) {
                migratePlan.dataset.loaded = "true";
                loadMigrateTargets();
            }
        });
        migrateCompute.addEventListener("change", loadMigratePlan);
    }

    // the tab a redirect points to; a template opens on its clone form
    restoreInstanceTab(document, location.hash || summary.dataset.opensOn, show_tab, load_osinfo);
    // none open (a template has no Power tab): the first section the page has
    if (!document.querySelector("#navbtn .nav-link.active")) {
        var first = document.querySelector("#navbtn .nav-link");
        if (first) { show_tab(first.getAttribute("data-bs-target")); }
    }
})();
