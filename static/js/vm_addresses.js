// The VM's addresses come once the page has loaded: the guest agent may take
// its whole timeout (instances.views.nic_addresses). An element with
// data-address-family shows those of the NICs in data-address-mac (MACs
// separated by spaces: not the guest's own bridges); data-empty when there
// are none.
(function () {
  const places = document.querySelectorAll("[data-address-family]");
  const show = (found) => {
    for (const place of places) {
      const nics = place.dataset.addressMac.split(" ").filter(Boolean).map((mac) => found[mac] || {});
      const addresses = nics.flatMap((nic) => nic[place.dataset.addressFamily] || []);
      place.textContent = addresses.join(", ") || place.dataset.empty;
      place.classList.toggle("text-body-secondary", !addresses.length);
    }
  };
  fetch(document.currentScript.dataset.url, {headers: {Accept: "application/json"}})
    .then((response) => (response.ok ? response.json() : {}))
    .catch(() => ({}))
    .then(show);
})();
