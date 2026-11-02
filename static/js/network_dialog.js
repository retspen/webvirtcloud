// The New network dialog (create_net_block.html).
// the IPv6 fields show with their box; a NAT or routed network needs a
// subnet (after the page's scripts, Bootstrap's among them)
document.addEventListener('DOMContentLoaded', function () {
    var ipv6 = document.getElementById('net_ipv6');
    function showIpv6() {
        var fields = document.getElementById('net_ipv6_fields');
        fields.hidden = !ipv6.checked;
        fields.querySelectorAll('input').forEach(function (input) { input.disabled = !ipv6.checked; });
        document.getElementById('net_subnet6').required = ipv6.checked;
    }
    ipv6.addEventListener('change', showIpv6);
    choiceDialog(document.getElementById('AddNetPool'), 'forward', function (mode) {
        document.getElementById('net_subnet').required = mode === 'nat' || mode === 'route';
        showIpv6();
    });
});
