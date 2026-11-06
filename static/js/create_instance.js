// The VM create form (create_instance_w2.html). Its URLs and messages are
// data attributes of #create-vm-form.
let images_control, networks_control;

function form_data() {
    return document.querySelector("#create-vm-form").dataset;
}

// the volume and network pickers: each chosen item is a row below its picker
function make_pickers() {
    images_control = new TomSelect('#image-control', {
        plugins: ['checkbox_options'],
        placeholder: form_data().addVolume,
        hidePlaceholder: false,
        onItemAdd: function (value) { if (!row_for("#img-list", value)) add_disk_row(value); },
        onItemRemove: function (value) { remove_row("#img-list", value); },
    });
    networks_control = new TomSelect('#network-control', {
        plugins: ['checkbox_options'],
        placeholder: form_data().addNetwork,
        hidePlaceholder: false,
        onItemAdd: function (value) { if (!row_for("#net-list", value)) add_network_row(value, ""); },
        onItemRemove: function (value) { remove_row("#net-list", value); },
    });
}

// a new VM starts with one interface: on "default" if the host has it
function add_first_network() {
    const names = Object.keys(networks_control.options);
    if (names.length) networks_control.addItem(names.includes("default") ? "default" : names[0]);
}

// Only the chosen disk source's fields are shown and sent: the others
// are disabled, so the browser neither submits nor validates them.
function show_source(source) {
    document.querySelectorAll(".disk-source").forEach(function (fieldset) {
        const on = fieldset.id === "source-" + source;
        fieldset.hidden = !on;
        fieldset.disabled = !on;
    });
    images_control[source === "existing" ? "enable" : "disable"]();
}

// A preset fills the size fields and picks a new disk; editing one of
// them afterwards leaves no preset marked as applied.
function apply_preset(button) {
    document.querySelector("#vm_vcpu").value = button.dataset.vcpu;
    document.querySelector("#vm_memory").value = button.dataset.memory;
    document.querySelector("#vm_hdd_size").value = button.dataset.disk;
    document.querySelector('input[name="disk_source"][value="new"]').checked = true;
    show_source("new");
    clear_presets();
    button.setAttribute("aria-pressed", "true");
    button.classList.replace("text-body", "btn-primary");
    document.querySelector("#preset-status").textContent =
        `${button.dataset.label}: ${button.dataset.vcpu} vCPU, ${button.dataset.memory} MiB, new ${button.dataset.disk} GiB disk`;
}

function clear_presets() {
    document.querySelectorAll(".preset").forEach(function (b) {
        b.setAttribute("aria-pressed", "false");
        b.classList.replace("btn-primary", "text-body");
    });
}

// Adding or deleting a flavor stays on the page: its reply replaces the
// presets and the dialog's list and form, and the dialog keeps the focus.
function show_flavors(reply) {
    const parts = new DOMParser().parseFromString(reply, "text/html");
    ["#presets", "#flavors"].forEach(sel => document.querySelector(sel).replaceWith(parts.querySelector(sel)));
    document.querySelector("#flavors .is-invalid, #flavors input:not([type=hidden])").focus();
}

// Disk and network rows: one per chosen volume or network, cloned from
// the page's row templates; the fields the server reads are derived
// from them in sync_lists.
function new_row(list, template, item) {
    const row = document.getElementById(template).content.firstElementChild.cloneNode(true);
    row.dataset.item = item;
    row.querySelector(".row-item").textContent = item;
    document.querySelector(list).append(row);
    return row;
}

function add_disk_row(volume) {
    const row = new_row("#img-list", "disk-row", volume);
    const bus = row.querySelector(".disk-bus");
    row.querySelector(".disk-device").addEventListener("change", function () {
        load_buses(bus, this.value);
    });
    row.querySelector(".row-remove").addEventListener("click", function () { images_control.removeItem(volume); });
    sync_lists();
    return row;
}

// a network row without a MAC gets a random one
function add_network_row(network, mac) {
    const row = new_row("#net-list", "network-row", network);
    const input = row.querySelector("input");
    input.value = mac;
    input.addEventListener("input", sync_lists);
    row.querySelector(".row-remove").addEventListener("click", function () { networks_control.removeItem(network); });
    if (!mac) random_mac(input);
    sync_lists();
    return row;
}

function row_for(list, item) {
    return [...document.querySelector(list).children].find(row => row.dataset.item === item);
}

function remove_row(list, item) {
    row_for(list, item)?.remove();
    sync_lists();
}

// volumes, networks and their MACs in row order; device<i> and bus<i>
// belong to the i-th volume
function sync_lists() {
    const disks = [...document.querySelector("#img-list").children];
    const nics = [...document.querySelector("#net-list").children];
    disks.forEach(function (row, i) {
        row.querySelector(".row-label").textContent = "hdd" + i;
        row.querySelector(".disk-device").name = "device" + i;
        row.querySelector(".disk-bus").name = "bus" + i;
    });
    nics.forEach(function (row, i) {
        row.querySelector(".row-label").textContent = "eth" + i;
    });
    document.querySelector("#images").value = disks.map(row => row.dataset.item).join(",");
    document.querySelector("#networks").value = nics.map(row => row.dataset.item).join(",");
    document.querySelector("#vm_mac").value = nics.map(row => row.querySelector("input").value).join(",");
}

// a MAC typed while the request was out stays
function random_mac(input) {
    $.getJSON(form_data().randomMacUrl, function (data) {
        if (!input.value) input.value = data['mac'];
        sync_lists();
    });
}

function volumes_url(pool) {
    return form_data().volumesUrl.replace("__pool__", encodeURIComponent(pool));
}

// A dependent list is empty while it loads, and a newer load aborts the
// older one: an answer for the previous choice never fills it.
function load_list(list, url, fill) {
    if (list.request) list.request.abort();
    list.request = $.getJSON(url, fill).fail(showLoadError);
    return list.request;
}

function load_volumes(pool) {
    images_control.clearOptions();  // keeps the chosen volumes
    return load_list(images_control, volumes_url(pool), function (data) {
        data['vols'].forEach(item => images_control.addOption({value: item, text: item}));
    });
}

// the copy goes into the template's pool unless the user picks another
function template_pool_chosen(pool) {
    select_value(document.querySelector("#template_storage"), pool);
    return load_templates(pool);
}

function load_templates(pool) {
    const list = document.querySelector("#template");
    list.replaceChildren();
    return load_list(list, volumes_url(pool), function (data) {
        list.replaceChildren(...data['vols'].map(item => new Option(item, item)));
    });
}

function load_buses(bus_select, disk_type) {
    const url = form_data().busesUrl.replace("__disk__", encodeURIComponent(disk_type));
    bus_select.replaceChildren();
    return load_list(bus_select, url, function (data) {
        bus_select.replaceChildren(...data['bus'].map(item => new Option(item, item)));
    });
}

// a value the loaded list no longer has is kept, not swapped for the first
function select_value(select, value) {
    if (![...select.options].some(option => option.value === value)) select.add(new Option(value, value));
    select.value = value;
}

// A refused form comes back as it was sent: its networks, volumes and
// template loaded first, any Advanced field with an error shown, then
// the focus on the first error.
function restore_submitted() {
    const form = document.querySelector("#create-vm-form");
    const element = document.getElementById("submitted-lists");
    const lists = element ? JSON.parse(element.textContent) : {networks: [], disks: [], pool: ""};
    lists.networks.forEach(function (nic) {
        networks_control.addOption({value: nic.name, text: nic.name});
        add_network_row(nic.name, nic.mac);
        networks_control.addItem(nic.name, true);
    });
    const loads = [];
    if (lists.pool) {
        select_value(document.querySelector("#storage-control"), lists.pool);
        loads.push(load_volumes(lists.pool).then(function () {
            return $.when(...lists.disks.map(function (disk) {
                images_control.addOption({value: disk.volume, text: disk.volume});
                const row = add_disk_row(disk.volume);
                images_control.addItem(disk.volume, true);
                const bus = row.querySelector(".disk-bus");
                select_value(row.querySelector(".disk-device"), disk.device);
                return load_buses(bus, disk.device).then(() => select_value(bus, disk.bus));
            }));
        }));
    }
    if (form.dataset.templatePool) {
        select_value(document.querySelector("#template_pool"), form.dataset.templatePool);
        loads.push(load_templates(form.dataset.templatePool).then(function () {
            select_value(document.querySelector("#template"), form.dataset.template);
        }));
    }
    const advanced = document.querySelector("#advanced");
    if (advanced.querySelector(".is-invalid")) bootstrap.Collapse.getOrCreateInstance(advanced, {toggle: false}).show();
    $.when(...loads).then(focusFirstError);
}

// without storage on the host there is no form to set up
if (document.querySelector("#create-vm-form")) {
    make_pickers();
    document.querySelectorAll('input[name="disk_source"]').forEach(function (radio) {
        radio.addEventListener("change", function () {
            show_source(this.value);
            if (this.value !== "new") clear_presets();  // its size is not sent
        });
    });
    show_source(document.querySelector('input[name="disk_source"]:checked').value);
    $("#create-vm-form").on("click", ".preset", function () { apply_preset(this); });
    $("#flavors-dialog").on("submit", "form", function (event) {
        event.preventDefault();
        $.post(this.action, $(this).serialize(), show_flavors).fail(() => this.submit());
    });
    ["#vm_vcpu", "#vm_memory", "#vm_hdd_size"].forEach(function (sel) {
        document.querySelector(sel).addEventListener("input", clear_presets);
    });
    document.querySelector("#storage-control").addEventListener("change", function () { load_volumes(this.value); });
    document.querySelector("#template_pool").addEventListener("change", function () { template_pool_chosen(this.value); });
    if (document.body.dataset.refused) restore_submitted();
    else add_first_network();
}
