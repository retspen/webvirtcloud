// The create wizard's first page (create_instance_w1.html): the machine
// types of the chosen architecture, Next to the form for them, and a VM
// defined from XML instead.

// the machine types of the chosen architecture, the default one selected;
// the list is empty while it loads, and a newer load aborts the older one
function load_machines(arch) {
    const next = document.querySelector("#next"), list = document.querySelector("#select_chipset");
    next.disabled = true;
    list.replaceChildren();
    if (list.request) list.request.abort();
    list.request = $.getJSON(list.dataset.machinesUrl.replace("__arch__", encodeURIComponent(arch)), function (data) {
        list.replaceChildren(...data['machines'].map(
            item => new Option(item, item, false, item === list.dataset.default)));
        next.disabled = !data['machines'].length;
    }).fail(showLoadError);
}

// placeholders, not "x86_64"/"pc": an architecture such as ppc64 contains "pc"
function create_url(arch, machine) {
    return document.querySelector("#next").dataset.createUrl
        .replace("__arch__", encodeURIComponent(arch)).replace("__machine__", encodeURIComponent(machine));
}

function goto_create() {
    window.location.href = create_url(document.querySelector("#select_archs").value,
                                      document.querySelector("#select_chipset").value);
}

const archs = document.querySelector("#select_archs");
archs.addEventListener("change", () => load_machines(archs.value));
document.querySelector("#next").addEventListener("click", goto_create);
load_machines(archs.value);

// the XML editor fills the form's field
const editor = ace.edit("editor");
editor.getSession().setMode("ace/mode/xml");
const xml_input = document.querySelector('input[name="dom_xml"]');
editor.getSession().on("change", function () {
    xml_input.value = editor.getSession().getValue();
});
// the editor measures itself when its section is shown
document.querySelector("#from-xml").addEventListener("shown.bs.collapse", () => editor.resize());
